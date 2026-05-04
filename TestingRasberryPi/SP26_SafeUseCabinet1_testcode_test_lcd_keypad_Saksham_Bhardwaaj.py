# test_lcd_keypad.py
# Raspberry Pi integration test — LCD display, 4×3 keypad, stepper motor,
# and HC-SR04 ultrasonic sensor all in one script.
# The operator types a 3-digit room number on the keypad; if the room exists
# in the database the conveyor belt runs forward until the sensor detects an
# item (< STOP_DISTANCE_CM cm), pauses, then returns to start.
# Used to validate full Pi-side hardware before connecting the Pico over UART.
#
# Hardware on the Pi (BCM GPIO numbering):
#   LCD   — I2C PCF8574 at 0x27
#   Keypad rows — GPIO5,6,13,19 (outputs)
#   Keypad cols — GPIO12,16,20  (inputs, pull-down)
#   Stepper DIR  — GPIO17
#   Stepper STEP — GPIO27
#   HC-SR04 TRIG — GPIO22
#   HC-SR04 ECHO — GPIO23

import sys
import os
import time

# Make Database module importable from the sibling Database/ directory
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'Database'))
from databaseAccess import room_exists, init_db

from RPLCD.i2c import CharLCD
import RPi.GPIO as GPIO

# ---------------------------------------------------------------------------
# Hardware configuration
# ---------------------------------------------------------------------------

# I2C LCD: 16 columns × 2 rows
lcd = CharLCD('PCF8574', 0x27, cols=16, rows=2)

# 4×3 matrix keypad — BCM GPIO pin numbers
KEYPAD = [
    ['1', '2', '3'],
    ['4', '5', '6'],
    ['7', '8', '9'],
    ['*', '0', '#'],
]
ROW_PINS = [5,  6,  13, 19]  # Driven HIGH one at a time during matrix scan
COL_PINS = [12, 16, 20]      # Read HIGH when the matching column key is pressed

# Stepper motor (A4988 driver) — BCM GPIO pin numbers
DIR_PIN  = 17   # HIGH = forward, LOW = reverse
STEP_PIN = 27   # Pulse HIGH/LOW to advance one microstep

# HC-SR04 ultrasonic sensor — BCM GPIO pin numbers
TRIG_PIN = 22
ECHO_PIN = 23

# Step timing — matches the Pico firmware values (8 ms/step ≈ 125 steps/sec)
STEP_DELAY_S  = 0.008       # Seconds between step pulses
PULSE_WIDTH_S = 0.000003    # 3 µs STEP pulse width

# Stop the belt if the sensor reads closer than this distance
STOP_DISTANCE_CM = 14

# Check the sensor at this interval while the belt is running
SENSOR_INTERVAL_S = 0.1

# ---------------------------------------------------------------------------
# GPIO setup
# ---------------------------------------------------------------------------
GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)

# Keypad
for pin in ROW_PINS:
    GPIO.setup(pin, GPIO.OUT, initial=GPIO.LOW)
for pin in COL_PINS:
    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)

# Stepper motor
GPIO.setup(DIR_PIN,  GPIO.OUT, initial=GPIO.LOW)
GPIO.setup(STEP_PIN, GPIO.OUT, initial=GPIO.LOW)

# HC-SR04
GPIO.setup(TRIG_PIN, GPIO.OUT, initial=GPIO.LOW)
GPIO.setup(ECHO_PIN, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)


# ---------------------------------------------------------------------------
# Keypad scanning
# ---------------------------------------------------------------------------

def read_key():
    """Scan the 4×3 matrix keypad and return the pressed key, or None."""
    for r_idx, row_pin in enumerate(ROW_PINS):
        GPIO.output(row_pin, GPIO.HIGH)   # Activate this row
        for c_idx, col_pin in enumerate(COL_PINS):
            if GPIO.input(col_pin) == GPIO.HIGH:
                GPIO.output(row_pin, GPIO.LOW)
                return KEYPAD[r_idx][c_idx]
        GPIO.output(row_pin, GPIO.LOW)    # Deactivate before moving to next row
    return None


# ---------------------------------------------------------------------------
# Stepper motor helpers
# ---------------------------------------------------------------------------

def set_direction(forward: bool):
    """Set the A4988 DIR pin: HIGH for forward (belt moves right), LOW for reverse."""
    GPIO.output(DIR_PIN, GPIO.HIGH if forward else GPIO.LOW)


def do_step():
    """Issue a single step pulse to the A4988."""
    GPIO.output(STEP_PIN, GPIO.HIGH)
    time.sleep(PULSE_WIDTH_S)
    GPIO.output(STEP_PIN, GPIO.LOW)


# ---------------------------------------------------------------------------
# HC-SR04 ultrasonic sensor
# ---------------------------------------------------------------------------

def read_distance_cm() -> float:
    """
    Fire the HC-SR04 and return distance in cm.
    Returns -1 if the echo times out (object out of range or sensor fault).
    Uses time.time() (seconds) instead of ticks_us because the Pi doesn't
    have MicroPython ticks — 100 ms timeouts are set via time.time() + 0.1.
    """
    GPIO.output(TRIG_PIN, GPIO.LOW)
    time.sleep(0.000002)   # 2 µs settle before trigger
    GPIO.output(TRIG_PIN, GPIO.HIGH)
    time.sleep(0.000010)   # 10 µs trigger pulse
    GPIO.output(TRIG_PIN, GPIO.LOW)

    # Wait for ECHO HIGH (start of return pulse), 100 ms timeout
    timeout = time.time() + 0.1
    while GPIO.input(ECHO_PIN) == GPIO.LOW:
        if time.time() > timeout:
            return -1
    pulse_start = time.time()

    # Wait for ECHO LOW (end of return pulse), 100 ms timeout
    timeout = time.time() + 0.1
    while GPIO.input(ECHO_PIN) == GPIO.HIGH:
        if time.time() > timeout:
            return -1
    pulse_end = time.time()

    # Distance = (round-trip time × speed of sound) / 2 = elapsed × 17150 cm/s
    return (pulse_end - pulse_start) * 17150


# ---------------------------------------------------------------------------
# Conveyor
# ---------------------------------------------------------------------------

def start_conveyor_and_wait(room_name: str):
    """
    Run the conveyor forward until the HC-SR04 detects an item, pause 1 second,
    then return the belt to start by reversing the step count.
    All status messages are shown on the I2C LCD.
    """
    lcd.clear()
    lcd.write_string("Delivering to")
    lcd.crlf()
    lcd.write_string("Room: " + room_name)

    set_direction(True)   # Forward
    steps_taken = 0
    last_sensor_time = time.time()

    # Drive belt forward until sensor detects item
    while True:
        do_step()
        steps_taken += 1
        time.sleep(STEP_DELAY_S)

        now = time.time()
        if now - last_sensor_time >= SENSOR_INTERVAL_S:
            last_sensor_time = now
            distance = read_distance_cm()
            # Stop only on a valid close reading (negative means no echo)
            if 0 < distance < STOP_DISTANCE_CM:
                print(f"Item detected at {distance:.1f} cm — stopping.")
                break

    # Hold at delivery position
    time.sleep(1)

    # Return belt to starting position
    lcd.clear()
    lcd.write_string("Returning belt")
    lcd.crlf()
    lcd.write_string("Room: " + room_name)

    set_direction(False)  # Reverse
    for _ in range(steps_taken):
        do_step()
        time.sleep(STEP_DELAY_S)

    lcd.clear()
    lcd.write_string("Item delivered!")
    lcd.crlf()
    lcd.write_string("Room: " + room_name)
    time.sleep(2)


# ---------------------------------------------------------------------------
# Keypad logic
# ---------------------------------------------------------------------------

buffer = []   # Accumulates digit key presses for the current room-number entry


def show_prompt():
    """Display the room-number entry prompt on the LCD."""
    lcd.clear()
    lcd.write_string("Enter room #:")
    lcd.crlf()
    lcd.write_string("_ _ _")


def handle_key(key):
    """
    Process a key press during room-number entry.
    '*' clears the input buffer.
    After 3 digits, validate the room and trigger a conveyor run if valid.
    """
    global buffer

    if key == '*':
        buffer = []
        show_prompt()
        return

    # Ignore non-digit keys (e.g. '#') during room entry
    if not key.isdigit():
        return

    buffer.append(key)
    # Show the digits typed so far on LCD line 2
    lcd.clear()
    lcd.write_string("Enter room #:")
    lcd.crlf()
    lcd.write_string("".join(buffer))

    # When 3 digits have been collected, validate and act
    if len(buffer) == 3:
        room_name = "".join(buffer)

        if room_exists(room_name):
            start_conveyor_and_wait(room_name)
        else:
            lcd.clear()
            lcd.write_string("Invalid Room!")
            lcd.crlf()
            lcd.write_string("Room: " + room_name)
            time.sleep(2)

        buffer = []
        show_prompt()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    init_db()        # Ensure database tables exist before querying
    show_prompt()    # Show the initial LCD prompt
    print("Running — press Ctrl+C to exit")
    print("Press '*' on keypad to clear entry")

    last_key = None
    try:
        while True:
            key = read_key()
            # Only handle newly pressed keys, not held keys
            if key is not None and key != last_key:
                handle_key(key)
            last_key = key
            time.sleep(0.05)  # 50 ms polling interval
    except KeyboardInterrupt:
        GPIO.cleanup()
        lcd.clear()
        print("Exited cleanly.")

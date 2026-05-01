import sys
import os
import time

# Make Database module importable from sibling directory
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'Database'))
from databaseAccess import room_exists, init_db

from RPLCD.i2c import CharLCD
import RPi.GPIO as GPIO

# ---------------------------------------------------------------------------
# Hardware configuration
# ---------------------------------------------------------------------------

# I2C LCD: 16 columns, 2 rows, I2C address 0x27
lcd = CharLCD('PCF8574', 0x27, cols=16, rows=2)

# 4x3 matrix keypad — BCM GPIO pin numbers (DO NOT CHANGE)
KEYPAD = [
    ['1', '2', '3'],
    ['4', '5', '6'],
    ['7', '8', '9'],
    ['*', '0', '#'],
]
ROW_PINS = [5,  6,  13, 19]
COL_PINS = [12, 16, 20]

# Stepper motor (A4988) — BCM GPIO pin numbers
DIR_PIN  = 17
STEP_PIN = 27

# HC-SR04 ultrasonic sensor — BCM GPIO pin numbers
TRIG_PIN = 22
ECHO_PIN = 23

# Motor timing — matches original Arduino values (8ms between steps)
STEP_DELAY_S  = 0.008       # seconds between steps
PULSE_WIDTH_S = 0.000003    # 3 µs STEP pulse

# Stop condition: item detected closer than this
STOP_DISTANCE_CM = 14

# How often to sample the sensor while running (seconds)
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

# Stepper
GPIO.setup(DIR_PIN,  GPIO.OUT, initial=GPIO.LOW)
GPIO.setup(STEP_PIN, GPIO.OUT, initial=GPIO.LOW)

GPIO.setup(TRIG_PIN, GPIO.OUT, initial=GPIO.LOW)
GPIO.setup(ECHO_PIN, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)


# ---------------------------------------------------------------------------
# Keypad scanning
# ---------------------------------------------------------------------------
def read_key():
    """Scan the keypad and return the pressed key, or None."""
    for r_idx, row_pin in enumerate(ROW_PINS):
        GPIO.output(row_pin, GPIO.HIGH)
        for c_idx, col_pin in enumerate(COL_PINS):
            if GPIO.input(col_pin) == GPIO.HIGH:
                GPIO.output(row_pin, GPIO.LOW)
                return KEYPAD[r_idx][c_idx]
        GPIO.output(row_pin, GPIO.LOW)
    return None


# ---------------------------------------------------------------------------
# Stepper motor helpers
# ---------------------------------------------------------------------------
def set_direction(forward: bool):
    GPIO.output(DIR_PIN, GPIO.HIGH if forward else GPIO.LOW)


def do_step():
    GPIO.output(STEP_PIN, GPIO.HIGH)
    time.sleep(PULSE_WIDTH_S)
    GPIO.output(STEP_PIN, GPIO.LOW)


# ---------------------------------------------------------------------------
# HC-SR04 ultrasonic sensor
# ---------------------------------------------------------------------------
def read_distance_cm() -> float:
    """Return distance in cm by polling ECHO pin with timeouts."""
    GPIO.output(TRIG_PIN, GPIO.LOW)
    time.sleep(0.000002)
    GPIO.output(TRIG_PIN, GPIO.HIGH)
    time.sleep(0.000010)
    GPIO.output(TRIG_PIN, GPIO.LOW)

    timeout = time.time() + 0.1
    while GPIO.input(ECHO_PIN) == GPIO.LOW:
        if time.time() > timeout:
            return -1
    pulse_start = time.time()

    timeout = time.time() + 0.1
    while GPIO.input(ECHO_PIN) == GPIO.HIGH:
        if time.time() > timeout:
            return -1
    pulse_end = time.time()

    return (pulse_end - pulse_start) * 17150


# ---------------------------------------------------------------------------
# Conveyor
# ---------------------------------------------------------------------------
def start_conveyor_and_wait(room_name: str):
    """
    Run conveyor forward until an item is detected (< STOP_DISTANCE_CM),
    pause 1 second, then return belt to starting position.
    """
    lcd.clear()
    lcd.write_string("Delivering to")
    lcd.crlf()
    lcd.write_string("Room: " + room_name)

    set_direction(True)
    steps_taken = 0
    last_sensor_time = time.time()

    # Run forward until item detected
    while True:
        do_step()
        steps_taken += 1
        time.sleep(STEP_DELAY_S)

        now = time.time()
        if now - last_sensor_time >= SENSOR_INTERVAL_S:
            last_sensor_time = now
            distance = read_distance_cm()
            if 0 < distance < STOP_DISTANCE_CM:
                print(f"Item detected at {distance:.1f} cm — stopping.")
                break

    # Pause 1 second after detection
    time.sleep(1)

    # Return belt to start position
    lcd.clear()
    lcd.write_string("Returning belt")
    lcd.crlf()
    lcd.write_string("Room: " + room_name)

    set_direction(False)
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
buffer = []


def show_prompt():
    lcd.clear()
    lcd.write_string("Enter room #:")
    lcd.crlf()
    lcd.write_string("_ _ _")


def handle_key(key):
    global buffer

    # '*' clears the current entry
    if key == '*':
        buffer = []
        show_prompt()
        return

    # Only accept digit keys; ignore '#'
    if not key.isdigit():
        return

    buffer.append(key)

    # Show digits typed so far on line 2
    lcd.clear()
    lcd.write_string("Enter room #:")
    lcd.crlf()
    lcd.write_string("".join(buffer))

    # Once 3 digits are entered, check the database
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
    init_db()
    show_prompt()
    print("Running — press Ctrl+C to exit")
    print("Press '*' on keypad to clear entry")

    last_key = None
    try:
        while True:
            key = read_key()
            if key is not None and key != last_key:
                handle_key(key)
            last_key = key
            time.sleep(0.05)
    except KeyboardInterrupt:
        GPIO.cleanup()
        lcd.clear()
        print("Exited cleanly.")

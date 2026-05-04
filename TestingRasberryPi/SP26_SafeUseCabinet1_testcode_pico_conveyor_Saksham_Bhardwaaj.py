# pico_conveyor.py
# MicroPython firmware for the Raspberry Pi Pico — single-direction conveyor.
# Waits for a "START" command from the Raspberry Pi over UART0, then runs the
# belt forward until sensors 1 or 2 detect a nearby item. After a 1-second
# pause at the delivery position the belt returns to its starting position by
# replaying the step count in reverse, then sends "DONE" back to the Pi.
# A physical button on GP9 also triggers a run independently of UART.
#
# Wiring:
#   Pico GP0 (TX) -> Pi RX (GPIO15)
#   Pico GP1 (RX) -> Pi TX (GPIO14)
#   Button: GP9 with internal pull-up (connect to GND to press)

from machine import Pin, UART
import time

# ---------------------------------------------------------------------------
# Hardware configuration
# ---------------------------------------------------------------------------

# Stepper motor (A4988 driver)
STEP_PIN = Pin(2, Pin.OUT)          # Step pulse output
DIR_PIN  = Pin(3, Pin.OUT)          # Direction: HIGH = forward, LOW = reverse
EN_PIN   = Pin(4, Pin.OUT, value=1) # Active LOW — motor starts disabled

# HC-SR04 sensors 1 and 2 (left/front side of belt)
TRIG1_PIN = Pin(5, Pin.OUT)
ECHO1_PIN = Pin(6, Pin.IN, Pin.PULL_DOWN)
TRIG2_PIN = Pin(7, Pin.OUT)
ECHO2_PIN = Pin(8, Pin.IN, Pin.PULL_DOWN)

# Manual button: press to simulate a START command without Pi involvement
BUTTON_PIN = Pin(9, Pin.IN, Pin.PULL_UP)  # Active LOW (pressed = 0)

# UART0 — communicates with the Raspberry Pi
uart = UART(0, baudrate=9600, tx=Pin(0), rx=Pin(1))

# ---------------------------------------------------------------------------
# Timing constants
# ---------------------------------------------------------------------------
STEP_DELAY_US  = 8000   # µs between step pulses (~125 steps/sec)
PULSE_WIDTH_US = 3      # 3 µs STEP pulse — minimum for A4988

# Stop if an item is detected closer than this
STOP_DISTANCE_CM = 14

# Check sensors every 100 ms while running (avoids slowing the step loop)
SENSOR_INTERVAL_US = 100000

# Pause at delivery position before returning (gives the item time to drop)
PAUSE_AFTER_DROP_MS = 1000

# ---------------------------------------------------------------------------
# Stepper motor helpers
# ---------------------------------------------------------------------------

def set_direction(forward: bool):
    """Set the DIR pin: HIGH for forward (right), LOW for reverse (left)."""
    DIR_PIN.value(1 if forward else 0)


def do_step():
    """Issue a single step pulse to the A4988."""
    STEP_PIN.value(1)
    time.sleep_us(PULSE_WIDTH_US)
    STEP_PIN.value(0)


# ---------------------------------------------------------------------------
# HC-SR04 distance measurement
# ---------------------------------------------------------------------------

def read_distance_cm(trig, echo):
    """
    Fire an HC-SR04 and return distance in cm.
    Returns -1 if the echo times out (object too far or sensor fault).
    """
    trig.value(0)
    time.sleep_us(2)
    trig.value(1)
    time.sleep_us(10)  # 10 µs HIGH trigger pulse
    trig.value(0)

    # Wait for echo to go HIGH (start of return pulse)
    timeout = time.ticks_add(time.ticks_us(), 100000)
    while echo.value() == 0:
        if time.ticks_diff(time.ticks_us(), timeout) > 0:
            return -1

    pulse_start = time.ticks_us()

    # Wait for echo to go LOW (end of return pulse)
    timeout = time.ticks_add(time.ticks_us(), 100000)
    while echo.value() == 1:
        if time.ticks_diff(time.ticks_us(), timeout) > 0:
            return -1

    # 0.01715 cm/µs = speed of sound (34300 cm/s) divided by 2 (round trip)
    duration = time.ticks_diff(time.ticks_us(), pulse_start)
    return duration * 0.01715


def item_detected():
    """Return True if either sensor detects something closer than STOP_DISTANCE_CM."""
    d1 = read_distance_cm(TRIG1_PIN, ECHO1_PIN)
    d2 = read_distance_cm(TRIG2_PIN, ECHO2_PIN)
    return (0 < d1 < STOP_DISTANCE_CM) or (0 < d2 < STOP_DISTANCE_CM)


# ---------------------------------------------------------------------------
# Conveyor logic
# ---------------------------------------------------------------------------

def run_conveyor():
    """
    Move belt forward until sensors 1 or 2 detect an item, pause, return to start,
    then send "DONE" to the Raspberry Pi over UART.
    """
    print("Conveyor starting...")
    uart.write("RUNNING\n")  # Notify Pi that a run has started

    EN_PIN.value(0)       # Enable motor driver (active LOW)
    set_direction(True)   # Always runs forward in this single-direction version
    steps_taken = 0
    last_sensor_us = time.ticks_us()

    # Run forward, checking sensors periodically
    while True:
        do_step()
        steps_taken += 1
        time.sleep_us(STEP_DELAY_US)

        now = time.ticks_us()
        if time.ticks_diff(now, last_sensor_us) >= SENSOR_INTERVAL_US:
            last_sensor_us = now
            d1 = read_distance_cm(TRIG1_PIN, ECHO1_PIN)
            d2 = read_distance_cm(TRIG2_PIN, ECHO2_PIN)
            print(f"S1: {d1:.1f} cm  S2: {d2:.1f} cm")
            if (0 < d1 < STOP_DISTANCE_CM) or (0 < d2 < STOP_DISTANCE_CM):
                print("Item detected — stopping.")
                break

    # Pause at delivery position (pause commented out in this version for testing)
    # time.sleep_ms(PAUSE_AFTER_DROP_MS)

    # Return belt to starting position using exact step count
    print("Returning to start...")
    set_direction(False)
    for _ in range(steps_taken):
        do_step()
        time.sleep_us(STEP_DELAY_US)

    EN_PIN.value(1)  # Disable driver when done
    print("Done.")
    uart.write("DONE\n")  # Signal the Raspberry Pi that the delivery is complete


# ---------------------------------------------------------------------------
# Main loop — listens for START over UART and monitors the manual button
# ---------------------------------------------------------------------------

print("Pico ready. Waiting for START command...")

last_button = 1  # Track previous button state for edge detection

while True:
    # Check for a "START" command from the Raspberry Pi
    if uart.any():
        command = uart.readline()
        if command:
            command = command.decode().strip()
            if command == "START":
                run_conveyor()

    # Button is active LOW: a falling edge (1 -> 0) triggers a run
    button = BUTTON_PIN.value()
    if button == 0 and last_button == 1:
        run_conveyor()
    last_button = button

    time.sleep_ms(50)  # Poll interval (avoids busy-spinning)

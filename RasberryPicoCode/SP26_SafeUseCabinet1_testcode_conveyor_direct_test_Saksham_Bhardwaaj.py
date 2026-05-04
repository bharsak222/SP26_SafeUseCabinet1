# conveyor_direct_test.py
# MicroPython standalone test for the Raspberry Pi Pico.
# Runs the conveyor belt in a single direction (set by DIRECTION_FORWARD),
# monitors all four HC-SR04 sensors, and stops when an item is detected.
# After stopping it returns the belt to the start position by replaying the
# same number of steps in reverse. No UART communication — output goes only
# to the Pico's USB serial console.
# Use this to verify sensor placement and stop-distance thresholds without
# needing the Raspberry Pi connected.

from machine import Pin
import time

# --- Stepper motor control pins (A4988 driver) ---
STEP_PIN = Pin(2, Pin.OUT)          # Pulse HIGH then LOW to advance one microstep
DIR_PIN  = Pin(3, Pin.OUT)          # HIGH = forward (RIGHT), LOW = reverse (LEFT)
EN_PIN   = Pin(4, Pin.OUT, value=1) # Active LOW: starts disabled for safety

# --- HC-SR04 ultrasonic sensor pins ---
TRIG1_PIN = Pin(5,  Pin.OUT)         # Sensor 1 — left-side trigger
ECHO1_PIN = Pin(6,  Pin.IN, Pin.PULL_DOWN)
TRIG2_PIN = Pin(7,  Pin.OUT)         # Sensor 2 — left-side echo
ECHO2_PIN = Pin(8,  Pin.IN, Pin.PULL_DOWN)
TRIG3_PIN = Pin(9,  Pin.OUT)         # Sensor 3 — right-side trigger
ECHO3_PIN = Pin(10, Pin.IN, Pin.PULL_DOWN)
TRIG4_PIN = Pin(11, Pin.OUT)         # Sensor 4 — right-side echo
ECHO4_PIN = Pin(12, Pin.IN, Pin.PULL_DOWN)

# --- Timing constants ---
STEP_DELAY_US  = 8000   # Microseconds between steps (~125 steps/sec)
PULSE_WIDTH_US = 3      # Minimum STEP high-time required by the A4988 (µs)

# --- Detection threshold ---
STOP_DISTANCE_CM = 7    # Stop the belt if any sensor reads closer than this (cm)

SENSOR_INTERVAL_US = 100000  # Check sensors every 100 ms to avoid blocking the step loop

# --- Pause after item detected ---
PAUSE_AFTER_DROP_MS = 1000  # Wait 1 second after detection before reversing

# Change this flag to choose which direction to run during this test
DIRECTION_FORWARD = True  # True = RIGHT, False = LEFT


# ---------------------------------------------------------------------------
# Stepper helpers
# ---------------------------------------------------------------------------

def set_direction(forward):
    """Set the A4988 DIR pin: HIGH for forward (right), LOW for reverse (left)."""
    DIR_PIN.value(1 if forward else 0)


def do_step():
    """Issue a single step pulse to the A4988 (3 µs HIGH, then LOW)."""
    STEP_PIN.value(1)
    time.sleep_us(PULSE_WIDTH_US)
    STEP_PIN.value(0)


# ---------------------------------------------------------------------------
# HC-SR04 distance measurement
# ---------------------------------------------------------------------------

def read_distance_cm(trig, echo):
    """
    Trigger an HC-SR04 measurement and return distance in cm.
    Returns -1 if the echo pulse times out (no object in range or wiring issue).
    """
    trig.value(0)
    time.sleep_us(2)   # Ensure TRIG is LOW before the trigger pulse
    trig.value(1)
    time.sleep_us(10)  # 10 µs HIGH pulse starts the measurement
    trig.value(0)

    # Wait for ECHO to go HIGH (pulse start), with 100 ms timeout
    timeout = time.ticks_add(time.ticks_us(), 100000)
    while echo.value() == 0:
        if time.ticks_diff(time.ticks_us(), timeout) > 0:
            return -1  # Echo never started — object too far or sensor not connected

    pulse_start = time.ticks_us()

    # Wait for ECHO to go LOW (pulse end), with 100 ms timeout
    timeout = time.ticks_add(time.ticks_us(), 100000)
    while echo.value() == 1:
        if time.ticks_diff(time.ticks_us(), timeout) > 0:
            return -1  # Echo never ended — object too close or sensor fault

    # Convert round-trip echo duration (µs) to distance (cm)
    # Speed of sound ≈ 0.01715 cm/µs (half of 34300 cm/s)
    return time.ticks_diff(time.ticks_us(), pulse_start) * 0.01715


# ---------------------------------------------------------------------------
# Main conveyor run (runs once then halts)
# ---------------------------------------------------------------------------

forward = DIRECTION_FORWARD
print("Starting conveyor test, forward=" + str(forward))

EN_PIN.value(0)        # Enable the A4988 driver (active LOW)
set_direction(forward)
steps_taken = 0
last_sensor_us = time.ticks_us()

# Step loop — runs until an item is detected by one of the sensors
while True:
    do_step()
    steps_taken += 1
    time.sleep_us(STEP_DELAY_US)

    now = time.ticks_us()
    # Only read sensors every SENSOR_INTERVAL_US to keep the step rate consistent
    if time.ticks_diff(now, last_sensor_us) >= SENSOR_INTERVAL_US:
        last_sensor_us = now
        if forward:
            # Moving right — watch sensors 3 and 4 (right side)
            d3 = read_distance_cm(TRIG3_PIN, ECHO3_PIN)
            d4 = read_distance_cm(TRIG4_PIN, ECHO4_PIN)
            print("S3: " + str(d3) + " cm  S4: " + str(d4) + " cm")
            stop = (0 < d3 < STOP_DISTANCE_CM) or (0 < d4 < STOP_DISTANCE_CM)
        else:
            # Moving left — watch sensors 1 and 2 (left side)
            d1 = read_distance_cm(TRIG1_PIN, ECHO1_PIN)
            d2 = read_distance_cm(TRIG2_PIN, ECHO2_PIN)
            print("S1: " + str(d1) + " cm  S2: " + str(d2) + " cm")
            stop = (0 < d1 < STOP_DISTANCE_CM) or (0 < d2 < STOP_DISTANCE_CM)

        if stop:
            print("Item detected — stopping.")
            break

# Pause at the delivery position to let the item settle
time.sleep_ms(PAUSE_AFTER_DROP_MS)
print("Steps taken: " + str(steps_taken))

# Return the belt to its starting position by stepping the same count in reverse
print("Returning to start...")
set_direction(not forward)
for _ in range(steps_taken):
    do_step()
    time.sleep_us(STEP_DELAY_US)

EN_PIN.value(1)  # Disable the A4988 driver when done
print("Done.")

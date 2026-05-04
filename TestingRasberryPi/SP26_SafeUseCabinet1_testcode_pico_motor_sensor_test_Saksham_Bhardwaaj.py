# pico_motor_sensor_test.py
# MicroPython test for the Raspberry Pi Pico.
# Runs the stepper motor continuously in one direction while reading sensors 3
# and 4 (right-side HC-SR04s) every 100 ms. Stops the motor and exits when
# either sensor detects an object closer than STOP_DISTANCE_CM.
# Used to validate that sensor placement and the stop threshold are correct
# before enabling UART communication and the full conveyor protocol.

from machine import Pin
import time

# --- Stepper motor control pins (A4988 driver) ---
STEP_PIN = Pin(2, Pin.OUT)          # Pulse HIGH/LOW to advance one microstep
DIR_PIN  = Pin(3, Pin.OUT)          # HIGH = forward, LOW = reverse
EN_PIN   = Pin(4, Pin.OUT, value=1) # Active LOW: starts disabled for safety

# --- HC-SR04 ultrasonic sensor pins ---
# Only sensors 3 and 4 are monitored in this test (right side of belt)
TRIG1_PIN = Pin(5,  Pin.OUT)
ECHO1_PIN = Pin(6,  Pin.IN, Pin.PULL_DOWN)
TRIG2_PIN = Pin(7,  Pin.OUT)
ECHO2_PIN = Pin(8,  Pin.IN, Pin.PULL_DOWN)
TRIG3_PIN = Pin(9,  Pin.OUT)         # Right-side sensor — primary stop trigger
ECHO3_PIN = Pin(10, Pin.IN, Pin.PULL_DOWN)
TRIG4_PIN = Pin(11, Pin.OUT)         # Right-side sensor — secondary stop trigger
ECHO4_PIN = Pin(12, Pin.IN, Pin.PULL_DOWN)

# --- Timing constants ---
STEP_DELAY_US  = 8000   # µs between step pulses (~125 steps/sec)
PULSE_WIDTH_US = 3      # Minimum STEP high-time for A4988 (µs)

# --- Stop threshold ---
STOP_DISTANCE_CM  = 14             # Stop if any watched sensor reads below this (cm)
SENSOR_INTERVAL_US = 100000        # Read sensors every 100 ms


def do_step():
    """Issue a single A4988 step pulse."""
    STEP_PIN.value(1)
    time.sleep_us(PULSE_WIDTH_US)
    STEP_PIN.value(0)


def read_distance_cm(trig, echo):
    """
    Trigger an HC-SR04 and return distance in cm.
    Returns -1 on timeout (no valid echo received).
    """
    trig.value(0)
    time.sleep_us(2)
    trig.value(1)
    time.sleep_us(10)  # 10 µs trigger pulse
    trig.value(0)

    # Wait for echo HIGH (start of return pulse)
    timeout = time.ticks_add(time.ticks_us(), 100000)
    while echo.value() == 0:
        if time.ticks_diff(time.ticks_us(), timeout) > 0:
            return -1

    pulse_start = time.ticks_us()

    # Wait for echo LOW (end of return pulse)
    timeout = time.ticks_add(time.ticks_us(), 100000)
    while echo.value() == 1:
        if time.ticks_diff(time.ticks_us(), timeout) > 0:
            return -1

    # Convert echo duration (µs) to distance (cm): 0.01715 cm/µs (half speed of sound)
    return time.ticks_diff(time.ticks_us(), pulse_start) * 0.01715


# Enable motor in reverse direction to verify both DIR states work
DIR_PIN.value(0)
EN_PIN.value(0)  # Enable the driver (active LOW)
print("Running — motor spinning, sensors active. Ctrl+C to stop.")

last_sensor_us = time.ticks_us()

# Main loop: step continuously while watching sensors 3 & 4 at 100 ms intervals
while True:
    do_step()
    time.sleep_us(STEP_DELAY_US)

    now = time.ticks_us()
    if time.ticks_diff(now, last_sensor_us) >= SENSOR_INTERVAL_US:
        last_sensor_us = now
        # Read both right-side sensors to catch the item regardless of exact position
        d3 = read_distance_cm(TRIG3_PIN, ECHO3_PIN)
        d4 = read_distance_cm(TRIG4_PIN, ECHO4_PIN)
        print(f"S3:{d3:.1f}  S4:{d4:.1f} cm")

        # Stop if either sensor is within the threshold (and returned a valid reading)
        if (
            (0 < d3 < STOP_DISTANCE_CM) or
            (0 < d4 < STOP_DISTANCE_CM)
        ):
            print("Item detected — stopping motor.")
            EN_PIN.value(1)  # Disable the driver (motor coils de-energized)
            break

print("Done.")

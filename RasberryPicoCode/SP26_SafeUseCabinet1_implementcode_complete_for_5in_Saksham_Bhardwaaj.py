# complete_for_5in.py
# MicroPython firmware for the Raspberry Pi Pico — 2-sensor bidirectional
# conveyor (production implementation for the 5-inch belt variant).
# Uses sensors 3 (right) and 4 (left) only. When moving RIGHT sensor 4 stops
# the belt; when moving LEFT sensor 3 stops it.
# NOTE: This version sends bare "DONE" (no step count) over UART, so the Pi's
# restock-email threshold is not triggered. Use complete_for_8in.py if step
# count reporting is required.
#
# Wiring:
#   Pico GP0 (TX) -> Pi RX (GPIO15)
#   Pico GP1 (RX) -> Pi TX (GPIO14)

from machine import Pin, UART
import time

# ---------------------------------------------------------------------------
# Hardware configuration
# ---------------------------------------------------------------------------

# Stepper motor (A4988 driver)
STEP_PIN = Pin(2, Pin.OUT)          # Pulse HIGH/LOW to advance one microstep
DIR_PIN  = Pin(3, Pin.OUT)          # HIGH = forward (RIGHT), LOW = reverse (LEFT)
EN_PIN   = Pin(4, Pin.OUT, value=1) # Active LOW — disabled at startup

# HC-SR04 sensor 3 — monitors the RIGHT delivery position
TRIG3_PIN = Pin(9,  Pin.OUT)
ECHO3_PIN = Pin(10, Pin.IN, Pin.PULL_DOWN)

# HC-SR04 sensor 4 — monitors the LEFT delivery position
TRIG4_PIN = Pin(11, Pin.OUT)
ECHO4_PIN = Pin(12, Pin.IN, Pin.PULL_DOWN)

# UART0 — communicates with Raspberry Pi at 9600 baud
# GP0 TX -> Pi GPIO15 (RX), GP1 RX <- Pi GPIO14 (TX)
uart = UART(0, baudrate=9600, tx=Pin(0), rx=Pin(1), timeout=100, timeout_char=100)

# ---------------------------------------------------------------------------
# Timing and threshold constants
# ---------------------------------------------------------------------------
STEP_DELAY_US  = 8000   # µs between step pulses (~125 steps/sec)
PULSE_WIDTH_US = 3      # Minimum A4988 STEP high-time (µs)

STOP_DISTANCE_CM    = 7       # Stop the belt when sensor reads below this (cm)
SENSOR_INTERVAL_US  = 100000  # Sample sensors every 100 ms (10 Hz)
PAUSE_AFTER_DROP_MS = 1000    # Dwell time at delivery position before reversing

# ---------------------------------------------------------------------------
# Stepper helpers
# ---------------------------------------------------------------------------

def set_direction(forward):
    """Set DIR pin: HIGH for right (forward), LOW for left (reverse)."""
    DIR_PIN.value(1 if forward else 0)


def do_step():
    """Issue a single A4988 step pulse."""
    STEP_PIN.value(1)
    time.sleep_us(PULSE_WIDTH_US)
    STEP_PIN.value(0)


# ---------------------------------------------------------------------------
# HC-SR04 distance measurement
# ---------------------------------------------------------------------------

def read_distance_cm(trig, echo):
    """
    Fire an HC-SR04 and return distance in cm.
    Returns -1 if the echo times out (object out of range or sensor fault).
    """
    trig.value(0)
    time.sleep_us(2)
    trig.value(1)
    time.sleep_us(10)  # 10 µs trigger pulse required by HC-SR04
    trig.value(0)

    # Wait for ECHO HIGH (start of return pulse), 100 ms timeout
    timeout = time.ticks_add(time.ticks_us(), 100000)
    while echo.value() == 0:
        if time.ticks_diff(time.ticks_us(), timeout) > 0:
            return -1

    pulse_start = time.ticks_us()

    # Wait for ECHO LOW (end of return pulse), 100 ms timeout
    timeout = time.ticks_add(time.ticks_us(), 100000)
    while echo.value() == 1:
        if time.ticks_diff(time.ticks_us(), timeout) > 0:
            return -1

    # Convert round-trip echo time (µs) to distance (cm)
    # 0.01715 cm/µs = speed of sound (34300 cm/s) / 2
    return time.ticks_diff(time.ticks_us(), pulse_start) * 0.01715


def item_detected(forward):
    """
    Check delivery-end sensors for an item.
    Moving RIGHT: sensor 4 (left side) signals arrival at left delivery point.
    Moving LEFT:  sensor 3 (right side) signals arrival at right delivery point.
    """
    if forward:
        # Moving right — stop on sensor 4 (left delivery end)
        d4 = read_distance_cm(TRIG4_PIN, ECHO4_PIN)
        return 0 < d4 < STOP_DISTANCE_CM
    else:
        # Moving left — stop on sensor 3 (right delivery end)
        d3 = read_distance_cm(TRIG3_PIN, ECHO3_PIN)
        return 0 < d3 < STOP_DISTANCE_CM


# ---------------------------------------------------------------------------
# Conveyor logic
# ---------------------------------------------------------------------------

def run_conveyor(forward):
    """
    Run the belt in the given direction until the delivery sensor triggers,
    pause at the delivery position, then return to start.
    Sends "DONE" (without step count) to the Pi when complete.
    """
    print("Conveyor starting, forward=" + str(forward))
    uart.write(b"RUNNING\n")  # Inform Pi that a delivery run has started

    EN_PIN.value(0)        # Enable A4988 driver (active LOW)
    set_direction(forward)
    steps_taken = 0
    last_sensor_us = time.ticks_us()

    # Step until the delivery sensor detects the item
    while True:
        do_step()
        steps_taken += 1
        time.sleep_us(STEP_DELAY_US)

        now = time.ticks_us()
        # Check sensors at the configured interval to keep the step rate steady
        if time.ticks_diff(now, last_sensor_us) >= SENSOR_INTERVAL_US:
            last_sensor_us = now
            if forward:
                d4 = read_distance_cm(TRIG4_PIN, ECHO4_PIN)
                print("S4: " + str(d4) + " cm")
                detected = 0 < d4 < STOP_DISTANCE_CM
            else:
                d3 = read_distance_cm(TRIG3_PIN, ECHO3_PIN)
                print("S3: " + str(d3) + " cm")
                detected = 0 < d3 < STOP_DISTANCE_CM
            if detected:
                print("Item detected — stopping.")
                break

    # Wait at delivery point to let the item settle before returning
    time.sleep_ms(PAUSE_AFTER_DROP_MS)
    print("Steps Taken: " + str(steps_taken))

    # Return belt to its starting position using the recorded step count
    print("Returning to start...")
    set_direction(not forward)
    for _ in range(steps_taken):
        do_step()
        time.sleep_us(STEP_DELAY_US)

    EN_PIN.value(1)  # Disable A4988 driver
    print("Done. Steps taken: " + str(steps_taken))
    # Send bare "DONE" — step count is not reported in this version
    uart.write(b"DONE\n")
    time.sleep_ms(500)  # Allow UART buffer to flush before returning


# ---------------------------------------------------------------------------
# Main loop — wait for START_RIGHT or START_LEFT from the Raspberry Pi
# ---------------------------------------------------------------------------

print("Pico ready. Waiting for START_RIGHT or START_LEFT...")

while True:
    if uart.any():
        command = uart.readline()
        if command:
            try:
                command = command.decode().strip()
            except UnicodeError:
                continue  # Skip garbled bytes
            if command == "START_RIGHT":
                run_conveyor(forward=True)
            elif command == "START_LEFT":
                run_conveyor(forward=False)

    time.sleep_ms(50)  # Poll interval — yield between UART checks

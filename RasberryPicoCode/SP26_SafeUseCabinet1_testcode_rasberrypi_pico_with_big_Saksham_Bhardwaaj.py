# rasberrypi_pico_with_big.py
# MicroPython firmware for the Raspberry Pi Pico — bidirectional conveyor
# with 4 HC-SR04 sensors and UART reporting.
# Waits on UART0 for START_RIGHT or START_LEFT commands from the Raspberry Pi.
# When moving RIGHT, sensors 1 & 2 (left side) trigger the stop.
# When moving LEFT,  sensors 3 & 4 (right side) trigger the stop.
# After stopping at the delivery point the belt returns to start by reversing
# the recorded step count, then sends "DONE:<steps>" back to the Pi so the
# Pi can check whether a restock email is needed.
#
# Wiring:
#   Pico GP0 (TX) -> Pi RX (GPIO15)
#   Pico GP1 (RX) -> Pi TX (GPIO14)

from machine import Pin, UART
import time

# ---------------------------------------------------------------------------
# Hardware configuration
# ---------------------------------------------------------------------------

# Stepper motor (A4988)
STEP_PIN = Pin(2, Pin.OUT)          # Step pulse output
DIR_PIN  = Pin(3, Pin.OUT)          # HIGH = forward (RIGHT), LOW = reverse (LEFT)
EN_PIN   = Pin(4, Pin.OUT, value=1) # Active LOW — disabled at startup

# HC-SR04 sensors: 1 & 2 on the left side, 3 & 4 on the right side
TRIG1_PIN = Pin(5,  Pin.OUT)
ECHO1_PIN = Pin(6,  Pin.IN, Pin.PULL_DOWN)
TRIG2_PIN = Pin(7,  Pin.OUT)
ECHO2_PIN = Pin(8,  Pin.IN, Pin.PULL_DOWN)
TRIG3_PIN = Pin(9,  Pin.OUT)
ECHO3_PIN = Pin(10, Pin.IN, Pin.PULL_DOWN)
TRIG4_PIN = Pin(11, Pin.OUT)
ECHO4_PIN = Pin(12, Pin.IN, Pin.PULL_DOWN)

# UART0 — communicates with Raspberry Pi at 9600 baud
uart = UART(0, baudrate=9600, tx=Pin(0), rx=Pin(1), timeout=100, timeout_char=100)

# ---------------------------------------------------------------------------
# Timing and threshold constants
# ---------------------------------------------------------------------------
STEP_DELAY_US  = 8000   # µs between step pulses (~125 steps/sec)
PULSE_WIDTH_US = 3      # Minimum STEP high-time for the A4988 (µs)

STOP_DISTANCE_CM    = 7       # Trigger a stop when a sensor reads below this (cm)
SENSOR_INTERVAL_US  = 100000  # Sample sensors every 100 ms
PAUSE_AFTER_DROP_MS = 1000    # Wait 1 s at delivery position before returning

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
    Trigger one HC-SR04 measurement and return distance in cm.
    Returns -1 if the echo times out (no object in range or sensor fault).
    """
    trig.value(0)
    time.sleep_us(2)
    trig.value(1)
    time.sleep_us(10)  # 10 µs HIGH trigger pulse required by HC-SR04
    trig.value(0)

    # Wait for ECHO to go HIGH (start of return pulse), 100 ms timeout
    timeout = time.ticks_add(time.ticks_us(), 100000)
    while echo.value() == 0:
        if time.ticks_diff(time.ticks_us(), timeout) > 0:
            return -1

    pulse_start = time.ticks_us()

    # Wait for ECHO to go LOW (end of return pulse), 100 ms timeout
    timeout = time.ticks_add(time.ticks_us(), 100000)
    while echo.value() == 1:
        if time.ticks_diff(time.ticks_us(), timeout) > 0:
            return -1

    # 0.01715 cm/µs = speed of sound (34300 cm/s) / 2 (round trip)
    duration = time.ticks_diff(time.ticks_us(), pulse_start)
    return duration * 0.01715


def item_detected(forward):
    """
    Check whether the delivery-end sensors have detected an item.
    When moving RIGHT (forward=True) check sensors 1 & 2 (left side of belt).
    When moving LEFT  (forward=False) check sensors 3 & 4 (right side of belt).
    """
    if forward:
        # Moving right — stop on sensors 1 & 2
        d1 = read_distance_cm(TRIG1_PIN, ECHO1_PIN)
        d2 = read_distance_cm(TRIG2_PIN, ECHO2_PIN)
        return (0 < d1 < STOP_DISTANCE_CM) or (0 < d2 < STOP_DISTANCE_CM)
    else:
        # Moving left — stop on sensors 3 & 4
        d3 = read_distance_cm(TRIG3_PIN, ECHO3_PIN)
        d4 = read_distance_cm(TRIG4_PIN, ECHO4_PIN)
        return (0 < d3 < STOP_DISTANCE_CM) or (0 < d4 < STOP_DISTANCE_CM)


# ---------------------------------------------------------------------------
# Conveyor logic
# ---------------------------------------------------------------------------

def run_conveyor(forward):
    """
    Run the belt in the given direction until item_detected() returns True,
    pause at the delivery position, return to start, then report DONE:<steps>
    to the Raspberry Pi so it can decide if a restock email is needed.
    """
    print("Conveyor starting, forward=" + str(forward))
    uart.write(b"RUNNING\n")  # Notify Pi that a run is in progress

    EN_PIN.value(0)        # Enable A4988 driver (active LOW)
    set_direction(forward)
    steps_taken = 0
    last_sensor_us = time.ticks_us()

    # Step until delivery sensor triggers
    while True:
        do_step()
        steps_taken += 1
        time.sleep_us(STEP_DELAY_US)

        now = time.ticks_us()
        if time.ticks_diff(now, last_sensor_us) >= SENSOR_INTERVAL_US:
            last_sensor_us = now
            if forward:
                # Moving right — monitor sensors 1 & 2
                d1 = read_distance_cm(TRIG1_PIN, ECHO1_PIN)
                d2 = read_distance_cm(TRIG2_PIN, ECHO2_PIN)
                print("S1: " + str(d1) + " cm  S2: " + str(d2) + " cm")
                detected = (0 < d1 < STOP_DISTANCE_CM) or (0 < d2 < STOP_DISTANCE_CM)
            else:
                # Moving left — monitor sensors 3 & 4
                d3 = read_distance_cm(TRIG3_PIN, ECHO3_PIN)
                d4 = read_distance_cm(TRIG4_PIN, ECHO4_PIN)
                print("S3: " + str(d3) + " cm  S4: " + str(d4) + " cm")
                detected = (0 < d3 < STOP_DISTANCE_CM) or (0 < d4 < STOP_DISTANCE_CM)
            if detected:
                print("Item detected — stopping.")
                break

    # Hold at delivery position to let the item settle
    time.sleep_ms(PAUSE_AFTER_DROP_MS)
    print("Steps Taken: " + str(steps_taken))

    # Return to start by reversing the exact step count
    print("Returning to start...")
    set_direction(not forward)
    for _ in range(steps_taken):
        do_step()
        time.sleep_us(STEP_DELAY_US)

    EN_PIN.value(1)  # Disable driver
    print("Done. Steps taken: " + str(steps_taken))
    # Report step count to Pi; Pi uses this to decide if a restock email is needed
    uart.write(("DONE:" + str(steps_taken) + "\n").encode())
    time.sleep_ms(500)  # Flush UART buffer before returning to the command loop


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
                continue  # Ignore garbled bytes
            if command == "START_RIGHT":
                run_conveyor(forward=True)
            elif command == "START_LEFT":
                run_conveyor(forward=False)

    time.sleep_ms(50)  # Poll interval

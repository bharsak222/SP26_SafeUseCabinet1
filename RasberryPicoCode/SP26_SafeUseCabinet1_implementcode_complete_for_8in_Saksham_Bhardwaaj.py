# complete_for_8in.py
# MicroPython firmware for the Raspberry Pi Pico — 4-sensor bidirectional
# conveyor (production implementation for the 8-inch belt variant).
# Uses sensors 1 & 2 (left side) and 3 & 4 (right side).
# Moving RIGHT stops on sensors 3 or 4; moving LEFT stops on sensors 1 or 2.
# After each delivery the step count is reported as "DONE:<steps>" so the
# Raspberry Pi can check a restock threshold and send an alert email if needed.
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
EN_PIN   = Pin(4, Pin.OUT, value=1) # Active LOW — disabled at startup for safety

# HC-SR04 sensors — 1 & 2 on the left side of the belt
TRIG1_PIN = Pin(5,  Pin.OUT)
ECHO1_PIN = Pin(6,  Pin.IN, Pin.PULL_DOWN)
TRIG2_PIN = Pin(7,  Pin.OUT)
ECHO2_PIN = Pin(8,  Pin.IN, Pin.PULL_DOWN)

# HC-SR04 sensors — 3 & 4 on the right side of the belt
TRIG3_PIN = Pin(9,  Pin.OUT)
ECHO3_PIN = Pin(10, Pin.IN, Pin.PULL_DOWN)
TRIG4_PIN = Pin(11, Pin.OUT)
ECHO4_PIN = Pin(12, Pin.IN, Pin.PULL_DOWN)

# UART0 — communicates with Raspberry Pi at 9600 baud
# Pico GP0 (TX) -> Pi GPIO15 (RX), Pico GP1 (RX) <- Pi GPIO14 (TX)
uart = UART(0, baudrate=9600, tx=Pin(0), rx=Pin(1), timeout=100, timeout_char=100)

# ---------------------------------------------------------------------------
# Timing and threshold constants
# ---------------------------------------------------------------------------
STEP_DELAY_US  = 8000   # µs between step pulses (~125 steps/sec)
PULSE_WIDTH_US = 3      # Minimum STEP high-time for the A4988 (µs)

STOP_DISTANCE_CM    = 7       # Stop when a sensor reads below this (cm)
SENSOR_INTERVAL_US  = 100000  # Sample sensors every 100 ms (10 Hz)
PAUSE_AFTER_DROP_MS = 1000    # Dwell at delivery position before reversing

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


# ---------------------------------------------------------------------------
# Conveyor logic
# ---------------------------------------------------------------------------

def run_conveyor(forward):
    """
    Run the belt in the given direction until the delivery-end sensors trigger,
    pause at the delivery position, return to start by reversing the step count,
    then send "DONE:<steps>" to the Pi.
    The Pi compares steps against RESTOCK_THRESHOLD and emails if exceeded.
    """
    print("Conveyor starting, forward=" + str(forward))
    uart.write(b"RUNNING\n")  # Notify Pi that a run has started

    EN_PIN.value(0)        # Enable A4988 driver (active LOW)
    set_direction(forward)
    steps_taken = 0
    last_sensor_us = time.ticks_us()

    # Step loop — runs until item detected at the delivery end
    while True:
        do_step()
        steps_taken += 1
        time.sleep_us(STEP_DELAY_US)

        now = time.ticks_us()
        # Only check sensors at SENSOR_INTERVAL_US to keep the step rate stable
        if time.ticks_diff(now, last_sensor_us) >= SENSOR_INTERVAL_US:
            last_sensor_us = now
            if forward:
                # Moving right — watch sensors 3 & 4 (right delivery end)
                d3 = read_distance_cm(TRIG3_PIN, ECHO3_PIN)
                d4 = read_distance_cm(TRIG4_PIN, ECHO4_PIN)
                print("S3: " + str(d3) + " cm  S4: " + str(d4) + " cm")
                detected = (0 < d3 < STOP_DISTANCE_CM) or (0 < d4 < STOP_DISTANCE_CM)
            else:
                # Moving left — watch sensors 1 & 2 (left delivery end)
                d1 = read_distance_cm(TRIG1_PIN, ECHO1_PIN)
                d2 = read_distance_cm(TRIG2_PIN, ECHO2_PIN)
                print("S1: " + str(d1) + " cm  S2: " + str(d2) + " cm")
                detected = (0 < d1 < STOP_DISTANCE_CM) or (0 < d2 < STOP_DISTANCE_CM)
            if detected:
                print("Item detected — stopping.")
                break

    # Dwell at delivery position so the item can drop before the belt returns
    time.sleep_ms(PAUSE_AFTER_DROP_MS)
    print("Steps Taken: " + str(steps_taken))

    # Return belt to start position by reversing the exact step count
    print("Returning to start...")
    set_direction(not forward)
    for _ in range(steps_taken):
        do_step()
        time.sleep_us(STEP_DELAY_US)

    EN_PIN.value(1)  # Disable A4988 driver
    print("Done. Steps taken: " + str(steps_taken))
    # Include step count in DONE message so Pi can check restock threshold
    uart.write(("DONE:" + str(steps_taken) + "\n").encode())
    time.sleep_ms(500)  # Allow UART TX buffer to flush before returning to loop


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
                continue  # Ignore garbled/incomplete bytes
            if command == "START_RIGHT":
                run_conveyor(forward=True)
            elif command == "START_LEFT":
                run_conveyor(forward=False)

    time.sleep_ms(50)  # Poll interval

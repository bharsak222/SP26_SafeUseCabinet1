from machine import Pin, UART
import time

# ---------------------------------------------------------------------------
# Hardware configuration
# ---------------------------------------------------------------------------

# Stepper motor (A4988)
STEP_PIN = Pin(2, Pin.OUT)
DIR_PIN  = Pin(3, Pin.OUT)
EN_PIN   = Pin(4, Pin.OUT, value=1)  # Active LOW — start disabled

# HC-SR04 sensor 1 (left side)
TRIG1_PIN = Pin(5,  Pin.OUT)
ECHO1_PIN = Pin(6,  Pin.IN, Pin.PULL_DOWN)

# HC-SR04 sensor 2 (left side)
TRIG2_PIN = Pin(7,  Pin.OUT)
ECHO2_PIN = Pin(8,  Pin.IN, Pin.PULL_DOWN)

# HC-SR04 sensor 3 (right side)
TRIG3_PIN = Pin(9,  Pin.OUT)
ECHO3_PIN = Pin(10, Pin.IN, Pin.PULL_DOWN)

# HC-SR04 sensor 4 (right side)
TRIG4_PIN = Pin(11, Pin.OUT)
ECHO4_PIN = Pin(12, Pin.IN, Pin.PULL_DOWN)

# UART serial communication with Raspberry Pi
# Pico GP0 (TX) -> Pi RX (GPIO15)
# Pico GP1 (RX) -> Pi TX (GPIO14)
uart = UART(0, baudrate=9600, tx=Pin(0), rx=Pin(1), timeout=100, timeout_char=100)

# Motor timing
STEP_DELAY_US  = 8000
PULSE_WIDTH_US = 3

# Stop condition
STOP_DISTANCE_CM = 7

# Sensor check interval
SENSOR_INTERVAL_US = 100000  # 100ms

# Pause after item detected before returning
PAUSE_AFTER_DROP_MS = 1000

# ---------------------------------------------------------------------------
# Stepper motor helpers
# ---------------------------------------------------------------------------

def set_direction(forward):
    DIR_PIN.value(1 if forward else 0)


def do_step():
    STEP_PIN.value(1)
    time.sleep_us(PULSE_WIDTH_US)
    STEP_PIN.value(0)


# ---------------------------------------------------------------------------
# HC-SR04 ultrasonic sensor
# ---------------------------------------------------------------------------

def read_distance_cm(trig, echo):
    trig.value(0)
    time.sleep_us(2)
    trig.value(1)
    time.sleep_us(10)
    trig.value(0)

    timeout = time.ticks_add(time.ticks_us(), 100000)
    while echo.value() == 0:
        if time.ticks_diff(time.ticks_us(), timeout) > 0:
            return -1

    pulse_start = time.ticks_us()

    timeout = time.ticks_add(time.ticks_us(), 100000)
    while echo.value() == 1:
        if time.ticks_diff(time.ticks_us(), timeout) > 0:
            return -1

    duration = time.ticks_diff(time.ticks_us(), pulse_start)
    return duration * 0.01715


# ---------------------------------------------------------------------------
# Conveyor logic
# ---------------------------------------------------------------------------

def run_conveyor(forward):
    """Run in given direction until item detected, pause, then return to start."""
    print("Conveyor starting, forward=" + str(forward))
    uart.write(b"RUNNING\n")

    EN_PIN.value(0)  # Enable motor
    set_direction(forward)
    steps_taken = 0
    last_sensor_us = time.ticks_us()

    # Run until item detected
    while True:
        do_step()
        steps_taken += 1
        time.sleep_us(STEP_DELAY_US)

        now = time.ticks_us()
        if time.ticks_diff(now, last_sensor_us) >= SENSOR_INTERVAL_US:
            last_sensor_us = now
            if forward:
                # Moving right — stop on sensors 3 & 4
                d3 = read_distance_cm(TRIG3_PIN, ECHO3_PIN)
                d4 = read_distance_cm(TRIG4_PIN, ECHO4_PIN)
                print("S3: " + str(d3) + " cm  S4: " + str(d4) + " cm")
                detected = (0 < d3 < STOP_DISTANCE_CM) or (0 < d4 < STOP_DISTANCE_CM)
            else:
                # Moving left — stop on sensors 1 & 2
                d1 = read_distance_cm(TRIG1_PIN, ECHO1_PIN)
                d2 = read_distance_cm(TRIG2_PIN, ECHO2_PIN)
                print("S1: " + str(d1) + " cm  S2: " + str(d2) + " cm")
                detected = (0 < d1 < STOP_DISTANCE_CM) or (0 < d2 < STOP_DISTANCE_CM)
            if detected:
                print("Item detected — stopping.")
                break

    # Pause after detection
    time.sleep_ms(PAUSE_AFTER_DROP_MS)
    print("Steps Taken: " + str(steps_taken))
    # Return to start (opposite direction)
    print("Returning to start...")
    set_direction(not forward)
    for _ in range(steps_taken):
        do_step()
        time.sleep_us(STEP_DELAY_US)

    EN_PIN.value(1)  # Disable motor
    print("Done. Steps taken: " + str(steps_taken))
    uart.write(("DONE:" + str(steps_taken) + "\n").encode())
    time.sleep_ms(500)  # Allow UART buffer to flush before returning


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

print("Pico ready. Waiting for START_RIGHT or START_LEFT...")

while True:
    if uart.any():
        command = uart.readline()
        if command:
            try:
                command = command.decode().strip()
            except UnicodeError:
                continue
            if command == "START_RIGHT":
                run_conveyor(forward=True)
            elif command == "START_LEFT":
                run_conveyor(forward=False)

    time.sleep_ms(50)

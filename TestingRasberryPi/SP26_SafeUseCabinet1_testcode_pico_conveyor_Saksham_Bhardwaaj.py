from machine import Pin, UART
import time

# ---------------------------------------------------------------------------
# Hardware configuration
# ---------------------------------------------------------------------------

# Stepper motor (A4988)
STEP_PIN = Pin(2, Pin.OUT)
DIR_PIN  = Pin(3, Pin.OUT)
EN_PIN   = Pin(4, Pin.OUT, value=1)  # Active LOW — start disabled

# HC-SR04 sensor 1
TRIG1_PIN = Pin(5, Pin.OUT)
ECHO1_PIN = Pin(6, Pin.IN, Pin.PULL_DOWN)

# HC-SR04 sensor 2
TRIG2_PIN = Pin(7, Pin.OUT)
ECHO2_PIN = Pin(8, Pin.IN, Pin.PULL_DOWN)

# Manual button (active LOW)
BUTTON_PIN = Pin(9, Pin.IN, Pin.PULL_UP)

# UART serial communication with Raspberry Pi
# Pi connects to Pico GP0 (TX) and GP1 (RX)
uart = UART(0, baudrate=9600, tx=Pin(0), rx=Pin(1))

# Motor timing
STEP_DELAY_US  = 8000   # 8ms between steps
PULSE_WIDTH_US = 3      # 3 µs STEP pulse

# Stop condition
STOP_DISTANCE_CM = 14

# Sensor check interval
SENSOR_INTERVAL_US = 100000  # 100ms

# Pause after item detected before returning
PAUSE_AFTER_DROP_MS = 1000

# ---------------------------------------------------------------------------
# Stepper motor helpers
# ---------------------------------------------------------------------------

def set_direction(forward: bool):
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


def item_detected():
    """Return True if either sensor detects something closer than STOP_DISTANCE_CM."""
    d1 = read_distance_cm(TRIG1_PIN, ECHO1_PIN)
    d2 = read_distance_cm(TRIG2_PIN, ECHO2_PIN)
    return (0 < d1 < STOP_DISTANCE_CM) or (0 < d2 < STOP_DISTANCE_CM)


# ---------------------------------------------------------------------------
# Conveyor logic
# ---------------------------------------------------------------------------

def run_conveyor():
    """Run forward until item detected, then return to start."""
    print("Conveyor starting...")
    uart.write("RUNNING\n")

    EN_PIN.value(0)  # Enable motor
    set_direction(True)
    steps_taken = 0
    last_sensor_us = time.ticks_us()

    # Run forward until item detected
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

    # Pause after detection
    # time.sleep_ms(PAUSE_AFTER_DROP_MS)

    # Return to start
    print("Returning to start...")
    set_direction(False)
    for _ in range(steps_taken):
        do_step()
        time.sleep_us(STEP_DELAY_US)

    EN_PIN.value(1)  # Disable motor
    print("Done.")
    uart.write("DONE\n")


# ---------------------------------------------------------------------------
# Main loop — wait for START command from Raspberry Pi
# ---------------------------------------------------------------------------

print("Pico ready. Waiting for START command...")

last_button = 1

while True:
    if uart.any():
        command = uart.readline()
        if command:
            command = command.decode().strip()
            if command == "START":
                run_conveyor()

    button = BUTTON_PIN.value()
    if button == 0 and last_button == 1:  # Button pressed
        run_conveyor()
    last_button = button

    time.sleep_ms(50)

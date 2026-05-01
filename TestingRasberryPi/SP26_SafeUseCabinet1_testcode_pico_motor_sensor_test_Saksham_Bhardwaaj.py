from machine import Pin
import time

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

# HC-SR04 sensor 3
TRIG3_PIN = Pin(9,  Pin.OUT)
ECHO3_PIN = Pin(10, Pin.IN, Pin.PULL_DOWN)

# HC-SR04 sensor 4
TRIG4_PIN = Pin(11, Pin.OUT)
ECHO4_PIN = Pin(12, Pin.IN, Pin.PULL_DOWN)

# Motor timing
STEP_DELAY_US  = 8000
PULSE_WIDTH_US = 3

STOP_DISTANCE_CM = 14
SENSOR_INTERVAL_US = 100000  # check sensors every 100ms


def do_step():
    STEP_PIN.value(1)
    time.sleep_us(PULSE_WIDTH_US)
    STEP_PIN.value(0)


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

    return time.ticks_diff(time.ticks_us(), pulse_start) * 0.01715


DIR_PIN.value(0)
EN_PIN.value(0)
print("Running — motor spinning, sensors active. Ctrl+C to stop.")

last_sensor_us = time.ticks_us()

while True:
    do_step()
    time.sleep_us(STEP_DELAY_US)

    now = time.ticks_us()
    if time.ticks_diff(now, last_sensor_us) >= SENSOR_INTERVAL_US:
        last_sensor_us = now
        d3 = read_distance_cm(TRIG3_PIN, ECHO3_PIN)
        d4 = read_distance_cm(TRIG4_PIN, ECHO4_PIN)
        print(f"S3:{d3:.1f}  S4:{d4:.1f} cm")

        if (
            (0 < d3 < STOP_DISTANCE_CM) or
            (0 < d4 < STOP_DISTANCE_CM)
        ):
            print("Item detected — stopping motor.")
            EN_PIN.value(1)
            break

print("Done.")

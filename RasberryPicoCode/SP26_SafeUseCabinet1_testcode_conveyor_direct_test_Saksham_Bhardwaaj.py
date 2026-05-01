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

# Stop condition
STOP_DISTANCE_CM = 7

# Sensor check interval
SENSOR_INTERVAL_US = 100000  # 100ms

# Pause after item detected before returning
PAUSE_AFTER_DROP_MS = 1000

# SET THIS: True = RIGHT, False = LEFT
DIRECTION_FORWARD = True


def set_direction(forward):
    DIR_PIN.value(1 if forward else 0)


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


forward = DIRECTION_FORWARD
print("Starting conveyor test, forward=" + str(forward))

EN_PIN.value(0)
set_direction(forward)
steps_taken = 0
last_sensor_us = time.ticks_us()

while True:
    do_step()
    steps_taken += 1
    time.sleep_us(STEP_DELAY_US)

    now = time.ticks_us()
    if time.ticks_diff(now, last_sensor_us) >= SENSOR_INTERVAL_US:
        last_sensor_us = now
        if forward:
            d3 = read_distance_cm(TRIG3_PIN, ECHO3_PIN)
            d4 = read_distance_cm(TRIG4_PIN, ECHO4_PIN)
            print("S3: " + str(d3) + " cm  S4: " + str(d4) + " cm")
            stop = (0 < d3 < STOP_DISTANCE_CM) or (0 < d4 < STOP_DISTANCE_CM)
        else:
            d1 = read_distance_cm(TRIG1_PIN, ECHO1_PIN)
            d2 = read_distance_cm(TRIG2_PIN, ECHO2_PIN)
            print("S1: " + str(d1) + " cm  S2: " + str(d2) + " cm")
            stop = (0 < d1 < STOP_DISTANCE_CM) or (0 < d2 < STOP_DISTANCE_CM)

        if stop:
            print("Item detected — stopping.")
            break

time.sleep_ms(PAUSE_AFTER_DROP_MS)
print("Steps taken: " + str(steps_taken))
print("Returning to start...")
set_direction(not forward)
for _ in range(steps_taken):
    do_step()
    time.sleep_us(STEP_DELAY_US)

EN_PIN.value(1)
print("Done.")

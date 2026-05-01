from machine import Pin
import time

# Stepper motor (A4988)
STEP_PIN = Pin(2, Pin.OUT)
DIR_PIN  = Pin(3, Pin.OUT)
EN_PIN   = Pin(4, Pin.OUT, value=1)  # Active LOW — start disabled

# Motor timing
STEP_DELAY_US  = 8000
PULSE_WIDTH_US = 3

DIR_PIN.value(1)   # Set direction
EN_PIN.value(0)    # Enable motor

print("Running continuously...")

while True:
    STEP_PIN.value(1)
    time.sleep_us(PULSE_WIDTH_US)
    STEP_PIN.value(0)
    time.sleep_us(STEP_DELAY_US)

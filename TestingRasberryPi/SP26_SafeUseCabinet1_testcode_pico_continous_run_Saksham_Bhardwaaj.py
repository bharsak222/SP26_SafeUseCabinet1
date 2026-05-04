# pico_continous_run.py
# MicroPython test program for the Raspberry Pi Pico.
# Spins the stepper motor (via an A4988 driver) continuously in the forward
# direction at a fixed step rate with no stopping condition.
# Used to verify that the motor wiring, A4988 driver enable/direction signals,
# and step timing are all correct before integrating sensors or UART logic.

from machine import Pin
import time

# --- Stepper motor control pins (A4988 driver) ---
STEP_PIN = Pin(2, Pin.OUT)          # Pulse HIGH then LOW to advance one microstep
DIR_PIN  = Pin(3, Pin.OUT)          # HIGH = forward, LOW = reverse
EN_PIN   = Pin(4, Pin.OUT, value=1) # Active LOW: HIGH = driver disabled (safe default)

# --- Step timing ---
# At 8 ms per step the motor runs at ~125 steps/sec in half-step mode.
# Increase STEP_DELAY_US to slow down, decrease to speed up.
STEP_DELAY_US  = 8000  # Microseconds to wait between step pulses
PULSE_WIDTH_US = 3     # Minimum STEP signal high-time required by the A4988 (µs)

DIR_PIN.value(1)  # Drive motor in the forward direction
EN_PIN.value(0)   # Enable the A4988 driver (active LOW)

print("Running continuously...")

while True:
    # Issue one step pulse: bring STEP HIGH for PULSE_WIDTH_US, then LOW
    STEP_PIN.value(1)
    time.sleep_us(PULSE_WIDTH_US)
    STEP_PIN.value(0)
    # Hold LOW for the remainder of the step period to set the step rate
    time.sleep_us(STEP_DELAY_US)

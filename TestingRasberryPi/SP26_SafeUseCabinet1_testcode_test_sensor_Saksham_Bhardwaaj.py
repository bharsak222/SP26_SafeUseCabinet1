# test_sensor.py
# Raspberry Pi test script for the HC-SR04 ultrasonic distance sensor.
# Continuously triggers the sensor and prints the measured distance in cm.
# Use this to verify sensor wiring and tune the STOP_DISTANCE_CM threshold
# before integrating the sensor into the full dispensing system.
#
# Wiring (BCM pin numbers):
#   TRIG -> GPIO22
#   ECHO -> GPIO23

import RPi.GPIO as GPIO
import time

# BCM GPIO pin assignments for the HC-SR04
TRIG = 22
ECHO = 23

# Configure GPIO using BCM numbering
GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)
GPIO.setup(TRIG, GPIO.OUT, initial=GPIO.LOW)  # TRIG starts LOW (idle)
GPIO.setup(ECHO, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)

try:
    while True:
        # --- Trigger a measurement ---
        # Pull TRIG LOW briefly to ensure a clean start, then send 10 µs HIGH pulse
        GPIO.output(TRIG, GPIO.LOW)
        time.sleep(0.000002)    # 2 µs settle time
        GPIO.output(TRIG, GPIO.HIGH)
        time.sleep(0.000010)    # 10 µs trigger pulse required by HC-SR04
        GPIO.output(TRIG, GPIO.LOW)

        # --- Wait for ECHO to go HIGH (marks start of return pulse), 100 ms timeout ---
        timeout = time.time() + 0.1
        while GPIO.input(ECHO) == GPIO.LOW:
            if time.time() > timeout:
                print("Timeout waiting for echo start")
                break
        else:
            pulse_start = time.time()
            # --- Wait for ECHO to go LOW (marks end of return pulse), 100 ms timeout ---
            timeout = time.time() + 0.1
            while GPIO.input(ECHO) == GPIO.HIGH:
                if time.time() > timeout:
                    print("Timeout waiting for echo end")
                    break
            else:
                # Distance (cm) = round-trip time (s) × speed of sound (34300 cm/s) / 2
                # Simplified: multiply elapsed seconds by 17150
                distance = (time.time() - pulse_start) * 17150
                print(f"Distance: {distance:.1f} cm")

        time.sleep(0.5)  # Pause 500 ms between measurements (~2 readings/sec)

except KeyboardInterrupt:
    GPIO.cleanup()  # Release all GPIO resources on Ctrl+C

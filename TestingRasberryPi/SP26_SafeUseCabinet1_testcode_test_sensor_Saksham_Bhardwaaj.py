import RPi.GPIO as GPIO
import time

TRIG = 22
ECHO = 23

GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)
GPIO.setup(TRIG, GPIO.OUT, initial=GPIO.LOW)
GPIO.setup(ECHO, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)

try:
    while True:
        GPIO.output(TRIG, GPIO.LOW)
        time.sleep(0.000002)
        GPIO.output(TRIG, GPIO.HIGH)
        time.sleep(0.000010)
        GPIO.output(TRIG, GPIO.LOW)

        timeout = time.time() + 0.1
        while GPIO.input(ECHO) == GPIO.LOW:
            if time.time() > timeout:
                print("Timeout waiting for echo start")
                break
        else:
            pulse_start = time.time()
            timeout = time.time() + 0.1
            while GPIO.input(ECHO) == GPIO.HIGH:
                if time.time() > timeout:
                    print("Timeout waiting for echo end")
                    break
            else:
                distance = (time.time() - pulse_start) * 17150
                print(f"Distance: {distance:.1f} cm")

        time.sleep(0.5)
except KeyboardInterrupt:
    GPIO.cleanup()

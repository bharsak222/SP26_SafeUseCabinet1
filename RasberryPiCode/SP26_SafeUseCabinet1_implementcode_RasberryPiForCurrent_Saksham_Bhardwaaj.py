import sys
import os
import time
import serial

# Make Database module importable from sibling directory
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'Database'))
from databaseAccess import room_exists, init_db
from gmail_send import send_email

ALERT_EMAIL    = 'bhardwaaj@wisc.edu'
STEPS_THRESHOLD = 3700

from RPLCD.i2c import CharLCD
import RPi.GPIO as GPIO

# ---------------------------------------------------------------------------
# Hardware configuration
# ---------------------------------------------------------------------------

# I2C LCD: 16 columns, 2 rows, I2C address 0x27
lcd = CharLCD('PCF8574', 0x27, cols=16, rows=2)

# 4x3 matrix keypad — BCM GPIO pin numbers (DO NOT CHANGE)
KEYPAD = [
    ['1', '2', '3'],
    ['4', '5', '6'],
    ['7', '8', '9'],
    ['*', '0', '#'],
]
ROW_PINS = [5,  6,  13, 19]
COL_PINS = [12, 16, 20]

# UART serial port to Raspberry Pi Pico
# Pi TX (GPIO14) -> Pico RX (GP1)
# Pi RX (GPIO15) -> Pico TX (GP0)
PICO_PORT    = '/dev/serial0'
PICO_BAUD    = 9600
PICO_TIMEOUT = 60   # seconds to wait for DONE before giving up

# ---------------------------------------------------------------------------
# GPIO setup
# ---------------------------------------------------------------------------
GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)

for pin in ROW_PINS:
    GPIO.setup(pin, GPIO.OUT, initial=GPIO.LOW)
for pin in COL_PINS:
    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)

# ---------------------------------------------------------------------------
# UART to Pico
# ---------------------------------------------------------------------------
pico = serial.Serial(PICO_PORT, PICO_BAUD, timeout=1)


def send_command(cmd: str):
    pico.reset_input_buffer()
    pico.write((cmd + '\n').encode())


def wait_for_done():
    """Wait for DONE:<steps> from Pico. Returns steps taken or -1 on timeout."""
    deadline = time.time() + PICO_TIMEOUT
    while time.time() < deadline:
        line = pico.readline().decode(errors='ignore').strip()
        if line:
            print("Pi received: " + repr(line))
        if line.startswith('DONE:'):
            try:
                return int(line.split(':')[1])
            except ValueError:
                return 0
        if line == 'DONE':
            return 0
    return -1


# ---------------------------------------------------------------------------
# Keypad scanning
# ---------------------------------------------------------------------------
def read_key():
    for r_idx, row_pin in enumerate(ROW_PINS):
        GPIO.output(row_pin, GPIO.HIGH)
        for c_idx, col_pin in enumerate(COL_PINS):
            if GPIO.input(col_pin) == GPIO.HIGH:
                GPIO.output(row_pin, GPIO.LOW)
                return KEYPAD[r_idx][c_idx]
        GPIO.output(row_pin, GPIO.LOW)
    return None


# ---------------------------------------------------------------------------
# Input logic
# ---------------------------------------------------------------------------
buffer = []
state = 'room'
current_room = ''


def handle_key(key):
    global state
    if state == 'room':
        handle_room_key(key)
    elif state == 'direction':
        handle_direction_key(key)


def show_prompt():
    lcd.clear()
    lcd.write_string("Enter room #:")
    lcd.crlf()
    lcd.write_string("_ _ _")


def handle_room_key(key):
    global buffer, state, current_room

    if key == '*':
        buffer = []
        show_prompt()
        return

    if not key.isdigit():
        return

    buffer.append(key)
    lcd.clear()
    lcd.write_string("Enter room #:")
    lcd.crlf()
    lcd.write_string("".join(buffer))

    if len(buffer) == 3:
        room_name = "".join(buffer)
        buffer = []

        if room_exists(room_name):
            current_room = room_name
            state = 'direction'
            lcd.clear()
            lcd.write_string("1=Right 2=Left")
            lcd.crlf()
            lcd.write_string("*=Cancel")
        else:
            lcd.clear()
            lcd.write_string("Invalid Room!")
            lcd.crlf()
            lcd.write_string("Room: " + room_name)
            time.sleep(2)
            show_prompt()


def handle_direction_key(key):
    global state

    if key == '*':
        state = 'room'
        show_prompt()
        return

    if key == '1':
        dispense(current_room, direction='RIGHT')
    elif key == '2':
        dispense(current_room, direction='LEFT')


def dispense(room_name: str, direction: str):
    global state

    lcd.clear()
    lcd.write_string("Dispensing")
    lcd.crlf()
    lcd.write_string(direction + " " + room_name)
    send_command('START_' + direction)

    steps = wait_for_done()
    if steps >= 0:
        lcd.clear()
        lcd.write_string("Delivered!")
        lcd.crlf()
        lcd.write_string("Room: " + room_name)
        if steps > STEPS_THRESHOLD:
            try:
                send_email(
                    ALERT_EMAIL,
                    "Conveyor Alert: Belt may need adjustment",
                    f"Room {room_name} ({direction}) took {steps} steps (threshold: {STEPS_THRESHOLD}). The belt may need to be checked."
                )
                print(f"Alert email sent: {steps} steps")
            except Exception as e:
                print("Email failed: " + str(e))
    else:
        lcd.clear()
        lcd.write_string("Timeout!")
        lcd.crlf()
        lcd.write_string("Check conveyor")

    time.sleep(2)
    state = 'room'
    show_prompt()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    init_db()
    show_prompt()

    last_key = None
    try:
        while True:
            key = read_key()
            if key is not None and key != last_key:
                handle_key(key)
            last_key = key
            time.sleep(0.05)
    except KeyboardInterrupt:
        pico.close()
        GPIO.cleanup()
        lcd.clear()
        print("Exited cleanly.")

# RasberryPiForCurrent.py
# Raspberry Pi main controller — single-dispenser production implementation.
# Presents a 3-digit room-number prompt on the I2C LCD, validates the room
# against the SQLite database, then lets the operator choose a belt direction
# (RIGHT or LEFT). Sends START_<DIR> over UART to the Pico, waits for
# "DONE:<steps>", and emails an alert if the step count exceeds STEPS_THRESHOLD
# (indicating the belt may have slipped or the dispenser is running low).
#
# State machine:
#   'room'      -> operator enters 3-digit room number
#   'direction' -> operator presses 1 (RIGHT) or 2 (LEFT)
#   (dispense)  -> belt runs; returns to 'room' when done

import sys
import os
import time
import serial

# Make Database module importable from the sibling Database/ directory
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'Database'))
from databaseAccess import room_exists, init_db
from gmail_send import send_email

ALERT_EMAIL    = 'bhardwaaj@wisc.edu'
STEPS_THRESHOLD = 3700  # Email alert if a run exceeds this many steps

from RPLCD.i2c import CharLCD
import RPi.GPIO as GPIO

# ---------------------------------------------------------------------------
# Hardware configuration
# ---------------------------------------------------------------------------

# I2C LCD: 16 columns, 2 rows, PCF8574 I2C expander at address 0x27
lcd = CharLCD('PCF8574', 0x27, cols=16, rows=2)

# 4×3 matrix keypad — BCM GPIO numbers
# Layout:  1 2 3
#          4 5 6
#          7 8 9
#          * 0 #
KEYPAD = [
    ['1', '2', '3'],
    ['4', '5', '6'],
    ['7', '8', '9'],
    ['*', '0', '#'],
]
ROW_PINS = [5,  6,  13, 19]  # Output pins driven HIGH one at a time
COL_PINS = [12, 16, 20]      # Input pins read to detect which column is pressed

# UART serial port connecting the Pi to the Raspberry Pi Pico
# Pi TX (GPIO14) -> Pico GP1 (RX), Pi RX (GPIO15) -> Pico GP0 (TX)
PICO_PORT    = '/dev/serial0'
PICO_BAUD    = 9600
PICO_TIMEOUT = 60   # Seconds to wait for DONE before declaring a timeout

# ---------------------------------------------------------------------------
# GPIO setup
# ---------------------------------------------------------------------------
GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)

# Keypad rows: configured as outputs so the Pi can drive them HIGH one at a time
for pin in ROW_PINS:
    GPIO.setup(pin, GPIO.OUT, initial=GPIO.LOW)
# Keypad columns: configured as inputs with pull-down; read HIGH when key pressed
for pin in COL_PINS:
    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)

# ---------------------------------------------------------------------------
# UART to Pico
# ---------------------------------------------------------------------------
pico = serial.Serial(PICO_PORT, PICO_BAUD, timeout=1)


def send_command(cmd: str):
    """Send a newline-terminated command string to the Pico over UART."""
    pico.reset_input_buffer()            # Discard stale RX data before sending
    pico.write((cmd + '\n').encode())


def wait_for_done():
    """
    Block until the Pico sends "DONE:<steps>" or bare "DONE".
    Returns the step count (int) on success, or -1 if PICO_TIMEOUT is exceeded.
    The step count is used to decide whether to send an alert email.
    """
    deadline = time.time() + PICO_TIMEOUT
    while time.time() < deadline:
        line = pico.readline().decode(errors='ignore').strip()
        if line:
            print("Pi received: " + repr(line))
        if line.startswith('DONE:'):
            try:
                return int(line.split(':')[1])
            except ValueError:
                return 0  # Malformed count — treat as zero
        if line == 'DONE':
            return 0
    return -1  # Timeout — Pico did not respond in time


# ---------------------------------------------------------------------------
# Keypad scanning
# ---------------------------------------------------------------------------

def read_key():
    """
    Scan the 4×3 keypad matrix by driving each row HIGH and checking columns.
    Returns the key character if a key is pressed, or None if none are pressed.
    """
    for r_idx, row_pin in enumerate(ROW_PINS):
        GPIO.output(row_pin, GPIO.HIGH)   # Assert this row
        for c_idx, col_pin in enumerate(COL_PINS):
            if GPIO.input(col_pin) == GPIO.HIGH:
                GPIO.output(row_pin, GPIO.LOW)
                return KEYPAD[r_idx][c_idx]  # Return pressed key
        GPIO.output(row_pin, GPIO.LOW)    # Deassert before moving to next row
    return None


# ---------------------------------------------------------------------------
# Input logic — simple two-state machine
# ---------------------------------------------------------------------------

buffer = []          # Accumulates key presses for the current field
state = 'room'       # Current state: 'room' or 'direction'
current_room = ''    # Room number confirmed against the database


def handle_key(key):
    """Route the key press to the handler for the current state."""
    global state
    if state == 'room':
        handle_room_key(key)
    elif state == 'direction':
        handle_direction_key(key)


def show_prompt():
    """Display the room-number entry prompt on the LCD."""
    lcd.clear()
    lcd.write_string("Enter room #:")
    lcd.crlf()
    lcd.write_string("_ _ _")


def handle_room_key(key):
    """
    Collect digits for the 3-digit room number.
    '*' clears the buffer. After 3 digits the room is validated against the DB;
    if valid, advance to 'direction' state; otherwise show an error and reset.
    """
    global buffer, state, current_room

    if key == '*':
        buffer = []
        show_prompt()
        return

    if not key.isdigit():
        return  # Ignore non-digit keys (e.g. '#') during room entry

    buffer.append(key)
    # Show running entry on line 2
    lcd.clear()
    lcd.write_string("Enter room #:")
    lcd.crlf()
    lcd.write_string("".join(buffer))

    if len(buffer) == 3:
        room_name = "".join(buffer)
        buffer = []

        if room_exists(room_name):
            current_room = room_name
            state = 'direction'  # Move to direction selection
            lcd.clear()
            lcd.write_string("1=Right 2=Left")
            lcd.crlf()
            lcd.write_string("*=Cancel")
        else:
            # Room not in database — show error and return to entry prompt
            lcd.clear()
            lcd.write_string("Invalid Room!")
            lcd.crlf()
            lcd.write_string("Room: " + room_name)
            time.sleep(2)
            show_prompt()


def handle_direction_key(key):
    """
    Accept '1' (RIGHT) or '2' (LEFT) to choose the dispense direction.
    '*' cancels and returns to room entry.
    """
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
    """
    Send the START command to the Pico, wait for completion, then show the
    result on the LCD. If step count exceeds STEPS_THRESHOLD, email an alert.
    """
    global state

    lcd.clear()
    lcd.write_string("Dispensing")
    lcd.crlf()
    lcd.write_string(direction + " " + room_name)
    send_command('START_' + direction)   # e.g. "START_RIGHT\n"

    steps = wait_for_done()
    if steps >= 0:
        lcd.clear()
        lcd.write_string("Delivered!")
        lcd.crlf()
        lcd.write_string("Room: " + room_name)
        # Warn if the belt traveled unusually far (may indicate low stock)
        if steps > STEPS_THRESHOLD:
            try:
                send_email(
                    ALERT_EMAIL,
                    "Conveyor Alert: Belt may need adjustment",
                    f"Room {room_name} ({direction}) took {steps} steps "
                    f"(threshold: {STEPS_THRESHOLD}). The belt may need to be checked."
                )
                print(f"Alert email sent: {steps} steps")
            except Exception as e:
                print("Email failed: " + str(e))
    else:
        # No DONE received within PICO_TIMEOUT seconds — likely a hardware fault
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
    init_db()       # Create tables if this is the first run
    show_prompt()   # Display the initial LCD prompt

    last_key = None
    try:
        while True:
            key = read_key()
            # Only act on a new key press (not a held key)
            if key is not None and key != last_key:
                handle_key(key)
            last_key = key
            time.sleep(0.05)  # 50 ms polling interval for the keypad
    except KeyboardInterrupt:
        pico.close()
        GPIO.cleanup()
        lcd.clear()
        print("Exited cleanly.")

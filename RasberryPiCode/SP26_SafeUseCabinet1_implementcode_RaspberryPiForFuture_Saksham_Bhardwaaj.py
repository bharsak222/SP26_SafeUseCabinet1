# RaspberryPiForFuture.py
# Raspberry Pi main controller — 5-dispenser production implementation.
# Supports up to 10 distinct items (0-9) spread across 5 Pico-controlled
# dispensers (one per UART port). Items 0-1 share dispenser 0, items 2-3 share
# dispenser 1, etc. The operator enters a room number then an item digit; the
# system looks up which dispenser and direction to use via ITEM_MAP.
#
# If a delivery run uses >= RESTOCK_THRESHOLD steps (75% of MAX_STEPS), an
# alert email is sent to prompt staff to refill that dispenser.
#
# Requires the following in /boot/firmware/config.txt to enable UART2-5:
#   dtoverlay=uart2
#   dtoverlay=uart3
#   dtoverlay=uart4
#   dtoverlay=uart5
#
# State machine:
#   'room' -> operator enters 3-digit room number
#   'item' -> operator presses a single digit (0-9) to select an item
#   (dispense) -> Pico runs; returns to 'room' when done

import sys
import os
import time
import serial

# Make Database module importable from the sibling Database/ directory
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'Database'))
from databaseAccess import room_exists, init_db
from gmail_send import send_email

from RPLCD.i2c import CharLCD
import RPi.GPIO as GPIO

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

ALERT_EMAIL       = 'bhardwaaj@wisc.edu'
MAX_STEPS         = 4100                    # Approximate steps for a full belt traverse
RESTOCK_THRESHOLD = int(MAX_STEPS * 0.75)  # 3075 steps — email if run exceeds this

# I2C LCD: 16 columns, 2 rows, PCF8574 expander at address 0x27
lcd = CharLCD('PCF8574', 0x27, cols=16, rows=2)

# 4×3 matrix keypad — BCM GPIO numbers
KEYPAD = [
    ['1', '2', '3'],
    ['4', '5', '6'],
    ['7', '8', '9'],
    ['*', '0', '#'],
]
ROW_PINS = [5,  6,  13, 19]  # Driven HIGH one at a time during scanning
COL_PINS = [12, 16, 20]      # Read HIGH when the corresponding column key is pressed

# ---------------------------------------------------------------------------
# 5 UART ports — one Pico per dispenser
# Each port maps to a dedicated GPIO pair (enabled via dtoverlay in config.txt)
# ---------------------------------------------------------------------------
PICO_PORTS = [
    '/dev/serial0',  # Dispenser 0 — GPIO14 TX / GPIO15 RX (built-in UART)
    '/dev/ttyAMA1',  # Dispenser 1 — GPIO0  TX / GPIO1  RX (dtoverlay=uart2)
    '/dev/ttyAMA2',  # Dispenser 2 — GPIO4  TX / GPIO5  RX (dtoverlay=uart3)
    '/dev/ttyAMA3',  # Dispenser 3 — GPIO8  TX / GPIO9  RX (dtoverlay=uart4)
    '/dev/ttyAMA4',  # Dispenser 4 — GPIO12 TX / GPIO13 RX (dtoverlay=uart5)
]
PICO_BAUD    = 9600
PICO_TIMEOUT = 60  # Seconds to wait for DONE before declaring a timeout

# ---------------------------------------------------------------------------
# Item-to-dispenser mapping
# Each item digit (0-9) maps to (dispenser_index, belt_direction).
# Each Pico handles 2 items: one dispensed RIGHT and one dispensed LEFT.
# ---------------------------------------------------------------------------
ITEM_MAP = {
    0: (0, 'RIGHT'),
    1: (0, 'LEFT'),
    2: (1, 'RIGHT'),
    3: (1, 'LEFT'),
    4: (2, 'RIGHT'),
    5: (2, 'LEFT'),
    6: (3, 'RIGHT'),
    7: (3, 'LEFT'),
    8: (4, 'RIGHT'),
    9: (4, 'LEFT'),
}

# Human-readable names shown on the LCD during dispensing
ITEM_NAMES = {
    0: 'Item 0',
    1: 'Item 1',
    2: 'Item 2',
    3: 'Item 3',
    4: 'Item 4',
    5: 'Item 5',
    6: 'Item 6',
    7: 'Item 7',
    8: 'Item 8',
    9: 'Item 9',
}

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
# Open all 5 serial ports at startup
# ---------------------------------------------------------------------------
picos = [serial.Serial(port, PICO_BAUD, timeout=1) for port in PICO_PORTS]


def send_command(pico, cmd: str):
    """Send a newline-terminated command to the specified Pico serial port."""
    pico.reset_input_buffer()
    pico.write((cmd + '\n').encode())


def wait_for_done(pico):
    """
    Wait up to PICO_TIMEOUT seconds for "DONE:<steps>" or bare "DONE" from a Pico.
    Returns the step count on success, or -1 on timeout.
    The Pi uses the step count to check whether a restock email is needed.
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
                return 0
        if line == 'DONE':
            return 0
    return -1  # Timeout


# ---------------------------------------------------------------------------
# Keypad scanning
# ---------------------------------------------------------------------------

def read_key():
    """
    Scan the 4×3 keypad by driving each row HIGH and reading column inputs.
    Returns the pressed key character, or None if no key is down.
    """
    for r_idx, row_pin in enumerate(ROW_PINS):
        GPIO.output(row_pin, GPIO.HIGH)
        for c_idx, col_pin in enumerate(COL_PINS):
            if GPIO.input(col_pin) == GPIO.HIGH:
                GPIO.output(row_pin, GPIO.LOW)
                return KEYPAD[r_idx][c_idx]
        GPIO.output(row_pin, GPIO.LOW)
    return None


# ---------------------------------------------------------------------------
# Input logic — two-state machine (room -> item -> dispense)
# ---------------------------------------------------------------------------

buffer       = []          # Digit accumulator for the current input field
state        = 'room'      # Current state: 'room' or 'item'
current_room = ''          # Room name validated against the database
current_item = None        # Item digit (0-9) selected by the operator


def handle_key(key):
    """Route key press to the handler for the current state."""
    global state
    if state == 'room':
        handle_room_key(key)
    elif state == 'item':
        handle_item_key(key)


def show_room_prompt():
    """Display the room-number entry prompt."""
    lcd.clear()
    lcd.write_string("Enter room #:")
    lcd.crlf()
    lcd.write_string("_ _ _")


def show_item_prompt():
    """Display the item-selection prompt after a valid room is confirmed."""
    lcd.clear()
    lcd.write_string("Item (0-9):")
    lcd.crlf()
    lcd.write_string("*=Cancel")


def handle_room_key(key):
    """
    Collect 3 digits for the room number.
    '*' clears the buffer. On the 3rd digit, validate the room against the DB.
    """
    global buffer, state, current_room

    if key == '*':
        buffer = []
        show_room_prompt()
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
            state = 'item'       # Valid room — advance to item selection
            show_item_prompt()
        else:
            lcd.clear()
            lcd.write_string("Invalid Room!")
            lcd.crlf()
            lcd.write_string("Room: " + room_name)
            time.sleep(2)
            show_room_prompt()


def handle_item_key(key):
    """
    Accept a single digit (0-9) to identify the item to dispense.
    '*' cancels and returns to room entry.
    """
    global state, current_item

    if key == '*':
        state = 'room'
        show_room_prompt()
        return

    if not key.isdigit():
        return

    item = int(key)
    if item not in ITEM_MAP:
        # Digit is not mapped to any dispenser slot
        lcd.clear()
        lcd.write_string("Invalid item!")
        lcd.crlf()
        lcd.write_string("Use 0-9")
        time.sleep(2)
        show_item_prompt()
        return

    current_item = item
    dispense(current_room, current_item)


def dispense(room_name: str, item: int):
    """
    Look up the dispenser and direction for the selected item, send the START
    command to the appropriate Pico, wait for completion, then update the LCD.
    Sends a restock alert email if the run step count meets RESTOCK_THRESHOLD.
    """
    global state

    dispenser_idx, direction = ITEM_MAP[item]
    item_name = ITEM_NAMES[item]
    pico = picos[dispenser_idx]   # Select the correct serial port

    lcd.clear()
    lcd.write_string("Dispensing")
    lcd.crlf()
    lcd.write_string(item_name[:16])  # Truncate to fit 16-char LCD width
    send_command(pico, 'START_' + direction)

    steps = wait_for_done(pico)
    if steps >= 0:
        lcd.clear()
        lcd.write_string("Delivered!")
        lcd.crlf()
        lcd.write_string("Room: " + room_name)
        # Check if the belt ran long enough to suggest the dispenser needs restocking
        if steps >= RESTOCK_THRESHOLD:
            try:
                send_email(
                    ALERT_EMAIL,
                    "Restock Alert: Dispenser " + str(dispenser_idx),
                    (
                        f"Dispenser {dispenser_idx} ({item_name}) took {steps} steps "
                        f"({steps}/{MAX_STEPS} = {steps/MAX_STEPS:.0%}), "
                        f"which is >= {RESTOCK_THRESHOLD} (75% of {MAX_STEPS}). "
                        f"Please restock."
                    )
                )
                print(f"Restock email sent: dispenser {dispenser_idx}, {steps} steps")
            except Exception as e:
                print("Email failed: " + str(e))
    else:
        # Pico did not respond within PICO_TIMEOUT — likely a hardware issue
        lcd.clear()
        lcd.write_string("Timeout!")
        lcd.crlf()
        lcd.write_string("Check conveyor")

    time.sleep(2)
    state = 'room'
    show_room_prompt()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    init_db()          # Create tables if this is the first run
    show_room_prompt() # Display the initial LCD prompt

    last_key = None
    try:
        while True:
            key = read_key()
            if key is not None and key != last_key:
                handle_key(key)
            last_key = key
            time.sleep(0.05)  # 50 ms polling interval
    except KeyboardInterrupt:
        for p in picos:
            p.close()      # Close all 5 serial ports cleanly
        GPIO.cleanup()
        lcd.clear()
        print("Exited cleanly.")

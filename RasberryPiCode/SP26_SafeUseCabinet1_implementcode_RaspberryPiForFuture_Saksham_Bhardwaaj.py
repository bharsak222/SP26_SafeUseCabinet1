import sys
import os
import time
import serial

# Make Database module importable from sibling directory
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'Database'))
from databaseAccess import room_exists, init_db
from gmail_send import send_email

from RPLCD.i2c import CharLCD
import RPi.GPIO as GPIO

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

ALERT_EMAIL      = 'bhardwaaj@wisc.edu'
MAX_STEPS        = 4100
RESTOCK_THRESHOLD = int(MAX_STEPS * 0.75)  # 3075 steps

# I2C LCD: 16 columns, 2 rows
lcd = CharLCD('PCF8574', 0x27, cols=16, rows=2)

# 4x3 matrix keypad — BCM GPIO pin numbers
KEYPAD = [
    ['1', '2', '3'],
    ['4', '5', '6'],
    ['7', '8', '9'],
    ['*', '0', '#'],
]
ROW_PINS = [5,  6,  13, 19]
COL_PINS = [12, 16, 20]

# ---------------------------------------------------------------------------
# 5 UART ports — one per Pico/dispenser
# Requires the following in /boot/firmware/config.txt:
#   dtoverlay=uart2
#   dtoverlay=uart3
#   dtoverlay=uart4
#   dtoverlay=uart5
# ---------------------------------------------------------------------------
PICO_PORTS = [
    '/dev/serial0',  # Dispenser 0 — GPIO14/15
    '/dev/ttyAMA1',  # Dispenser 1 — GPIO0/1   (dtoverlay=uart2)
    '/dev/ttyAMA2',  # Dispenser 2 — GPIO4/5   (dtoverlay=uart3)
    '/dev/ttyAMA3',  # Dispenser 3 — GPIO8/9   (dtoverlay=uart4)
    '/dev/ttyAMA4',  # Dispenser 4 — GPIO12/13 (dtoverlay=uart5)
]
PICO_BAUD    = 9600
PICO_TIMEOUT = 60

# Map item number (0-9) -> (dispenser_index, direction)
# Each dispenser handles 2 items: RIGHT and LEFT
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
# Open all 5 serial ports
# ---------------------------------------------------------------------------
picos = [serial.Serial(port, PICO_BAUD, timeout=1) for port in PICO_PORTS]


def send_command(pico, cmd: str):
    pico.reset_input_buffer()
    pico.write((cmd + '\n').encode())


def wait_for_done(pico):
    """Wait for DONE or DONE:<steps> from Pico. Returns steps or -1 on timeout."""
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
buffer       = []
state        = 'room'
current_room = ''
current_item = None


def handle_key(key):
    global state
    if state == 'room':
        handle_room_key(key)
    elif state == 'item':
        handle_item_key(key)


def show_room_prompt():
    lcd.clear()
    lcd.write_string("Enter room #:")
    lcd.crlf()
    lcd.write_string("_ _ _")


def show_item_prompt():
    lcd.clear()
    lcd.write_string("Item (0-9):")
    lcd.crlf()
    lcd.write_string("*=Cancel")


def handle_room_key(key):
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
            state = 'item'
            show_item_prompt()
        else:
            lcd.clear()
            lcd.write_string("Invalid Room!")
            lcd.crlf()
            lcd.write_string("Room: " + room_name)
            time.sleep(2)
            show_room_prompt()


def handle_item_key(key):
    global state, current_item

    if key == '*':
        state = 'room'
        show_room_prompt()
        return

    if not key.isdigit():
        return

    item = int(key)
    if item not in ITEM_MAP:
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
    global state

    dispenser_idx, direction = ITEM_MAP[item]
    item_name = ITEM_NAMES[item]
    pico = picos[dispenser_idx]

    lcd.clear()
    lcd.write_string("Dispensing")
    lcd.crlf()
    lcd.write_string(item_name[:16])
    send_command(pico, 'START_' + direction)

    steps = wait_for_done(pico)
    if steps >= 0:
        lcd.clear()
        lcd.write_string("Delivered!")
        lcd.crlf()
        lcd.write_string("Room: " + room_name)
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
    init_db()
    show_room_prompt()

    last_key = None
    try:
        while True:
            key = read_key()
            if key is not None and key != last_key:
                handle_key(key)
            last_key = key
            time.sleep(0.05)
    except KeyboardInterrupt:
        for p in picos:
            p.close()
        GPIO.cleanup()
        lcd.clear()
        print("Exited cleanly.")

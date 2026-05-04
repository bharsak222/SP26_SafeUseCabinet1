# UART_Test_Pi.py
# Raspberry Pi test script for verifying UART communication with the Pico.
# Sends a list of test messages over /dev/serial0 at 9600 baud and checks
# that the Pico echoes each one back with the expected "PICO_GOT: <msg>" prefix.
# Run this on the Pi while UART_Test_Pico.py is running on the Pico.
#
# Wiring:
#   Pi TX (GPIO14) -> Pico GP1 (RX)
#   Pi RX (GPIO15) -> Pico GP0 (TX)

import serial
import time

# Serial port and baud rate — must match the UART settings in UART_Test_Pico.py
PICO_PORT = '/dev/serial0'
PICO_BAUD = 9600

# Open serial port with a 2-second read timeout so readline() won't block forever
pico = serial.Serial(PICO_PORT, PICO_BAUD, timeout=2)
time.sleep(1)  # Allow the port to settle after opening before sending data

# Test messages: plain strings plus actual protocol commands used in production
TEST_MESSAGES = ["HELLO", "START_RIGHT", "START_LEFT", "PING"]

print("Pi UART test starting...")
print(f"Port: {PICO_PORT} at {PICO_BAUD} baud\n")

for msg in TEST_MESSAGES:
    print(f"Sending:  {msg}")
    pico.reset_input_buffer()           # Discard any stale bytes in the RX buffer
    pico.write((msg + '\n').encode())   # Send message terminated with newline

    # Block until a response line arrives or the timeout expires
    response = pico.readline().decode('utf-8', errors='ignore').strip()
    if response:
        print(f"Received: {response}")
        # The Pico should echo back exactly "PICO_GOT: <original_message>"
        if response == "PICO_GOT: " + msg:
            print("  PASS")
        else:
            print("  UNEXPECTED RESPONSE")
    else:
        print("  FAIL — no response (timeout)")

    print()
    time.sleep(0.5)  # Short gap between test messages

pico.close()
print("Done.")

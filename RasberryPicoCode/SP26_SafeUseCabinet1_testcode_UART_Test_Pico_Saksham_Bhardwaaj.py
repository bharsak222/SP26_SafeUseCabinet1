# UART_Test_Pico.py
# MicroPython test program for the Raspberry Pi Pico.
# Listens on UART0 (GP0 TX, GP1 RX at 9600 baud) and echoes every received
# line back to the Raspberry Pi prefixed with "PICO_GOT: ".
# Run this alongside UART_Test_Pi.py on the Pi to verify that the serial
# wiring between the two boards is correct before deploying the full system.
#
# Wiring:
#   Pico GP0 (TX) -> Pi RX (GPIO15)
#   Pico GP1 (RX) -> Pi TX (GPIO14)

from machine import Pin, UART
import time

# UART0: GP0=TX -> Pi RX (GPIO15), GP1=RX -> Pi TX (GPIO14)
# timeout/timeout_char set to 100 ms so readline() doesn't block indefinitely
uart = UART(0, baudrate=9600, tx=Pin(0), rx=Pin(1), timeout=100, timeout_char=100)

print("Pico UART test ready.")
print("Waiting for messages from Pi...")

while True:
    # Only attempt a read when at least one byte has arrived
    if uart.any():
        data = uart.readline()
        if data:
            try:
                msg = data.decode().strip()  # Decode bytes to string, trim newline
            except UnicodeError:
                continue  # Ignore garbled/incomplete bytes and wait for next line
            print("Received: " + msg)
            # Echo the message back so the Pi can verify round-trip communication
            response = "PICO_GOT: " + msg + "\n"
            uart.write(response.encode())
            print("Sent: " + response.strip())

    time.sleep_ms(50)  # Brief yield to avoid busy-spinning on the UART buffer

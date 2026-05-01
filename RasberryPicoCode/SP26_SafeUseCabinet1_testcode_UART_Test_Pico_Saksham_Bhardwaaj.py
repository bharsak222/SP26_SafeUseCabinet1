from machine import Pin, UART
import time

# UART0: GP0=TX -> Pi RX (GPIO15), GP1=RX -> Pi TX (GPIO14)
uart = UART(0, baudrate=9600, tx=Pin(0), rx=Pin(1), timeout=100, timeout_char=100)

print("Pico UART test ready.")
print("Waiting for messages from Pi...")

while True:
    # Echo anything received back to the Pi with a prefix
    if uart.any():
        data = uart.readline()
        if data:
            try:
                msg = data.decode().strip()
            except UnicodeError:
                continue
            print("Received: " + msg)
            response = "PICO_GOT: " + msg + "\n"
            uart.write(response.encode())
            print("Sent: " + response.strip())

    time.sleep_ms(50)

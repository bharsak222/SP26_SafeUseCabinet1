import serial
import time

# Pi TX (GPIO14) -> Pico RX (GP1)
# Pi RX (GPIO15) -> Pico TX (GP0)
PICO_PORT = '/dev/serial0'
PICO_BAUD = 9600

pico = serial.Serial(PICO_PORT, PICO_BAUD, timeout=2)
time.sleep(1)  # Give serial port time to settle

TEST_MESSAGES = ["HELLO", "START_RIGHT", "START_LEFT", "PING"]

print("Pi UART test starting...")
print(f"Port: {PICO_PORT} at {PICO_BAUD} baud\n")

for msg in TEST_MESSAGES:
    print(f"Sending:  {msg}")
    pico.reset_input_buffer()
    pico.write((msg + '\n').encode())

    response = pico.readline().decode('utf-8', errors='ignore').strip()
    if response:
        print(f"Received: {response}")
        if response == "PICO_GOT: " + msg:
            print("  PASS")
        else:
            print("  UNEXPECTED RESPONSE")
    else:
        print("  FAIL — no response (timeout)")

    print()
    time.sleep(0.5)

pico.close()
print("Done.")

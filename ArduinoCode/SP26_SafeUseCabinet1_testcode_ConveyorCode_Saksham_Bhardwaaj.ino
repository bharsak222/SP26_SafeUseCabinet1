// ===== SP26 SafeUseCabinet — Conveyor Belt Controller =====
// Arduino (Uno/Nano) firmware for the A4988 stepper motor driver + HC-SR04
// ultrasonic sensor + serial interface to the Raspberry Pi.
//
// Half-step microstepping is set by the A4988 MS pins wired externally:
//   MS1=HIGH, MS2=LOW, MS3=LOW
//
// Pin assignments:
//   D2  -> A4988 DIR   (direction)
//   D3  -> A4988 STEP  (step pulse)
//   D5  -> Button      (one side GND, other side D5 with INPUT_PULLUP)
//   D12 <- HC-SR04 ECHO
//   D13 -> HC-SR04 TRIG
//
// Protocol with Raspberry Pi (9600 baud over USB serial):
//   Pi sends "START\n"  -> begin belt in forward direction
//   Pi sends "STOP\n"   -> stop belt immediately
//   Arduino sends "DONE\n" -> delivery complete (belt returned to start)
//
// Behavior on item detection (distance < STOP_DISTANCE_CM):
//   1. Stop the belt immediately.
//   2. Pause PAUSE_AFTER_DROP_MS milliseconds for the item to drop.
//   3. Return the belt to the starting position using the step counter.
//   4. Send "DONE\n" to the Raspberry Pi.
//
// The manual button on D5 also starts/stops the belt independently of serial.

#define dirPin    2
#define stepPin   3
#define buttonPin 5

const int trigPin = 13;
const int echoPin = 12;

// Motor speed: bigger delay = slower. 8 ms/step ≈ 125 steps/sec.
const unsigned int stepDelayUs   = 8000;   // Forward step period (µs)
const unsigned int returnDelayUs = 8000;   // Return step period (µs, same speed)
const unsigned int pulseWidthUs  = 3;      // STEP high-time required by A4988 (µs)

// Button debounce: ignore bounces shorter than this window
const unsigned long debounceMs = 25;

// Ultrasonic sensor: check ~10 times per second with a safe echo timeout
const unsigned long sensorIntervalMs = 100;     // How often to fire the sensor (ms)
const unsigned long echoTimeoutUs    = 25000UL; // Max echo wait (25 ms ≈ ~4 m range)

// Stop the belt if an object is detected closer than this
const int STOP_DISTANCE_CM = 14;

// How long to dwell at the delivery position before returning (ms)
const unsigned long pauseAfterDropMs = 1000;

bool running = false;

// Tracks the current DIR pin state (true = forward)
bool directionForward = true;

// Step position relative to the starting point; used to return home
long positionSteps = 0;

// Debounce state variables
bool lastStable   = HIGH;
bool lastRead     = HIGH;
unsigned long lastChangeMs = 0;

// Non-blocking timing for step pulses and sensor reads
unsigned long lastStepMicros = 0;
unsigned long lastSensorMs   = 0;


// ---------------------------------------------------------------------------
// setDirection — write the DIR pin and update the tracking variable
// ---------------------------------------------------------------------------
void setDirection(bool forward) {
  directionForward = forward;
  digitalWrite(dirPin, directionForward ? HIGH : LOW);
}


// ---------------------------------------------------------------------------
// doStepPulseAndCount — issue one step pulse and update positionSteps
// positionSteps tracks how many steps we are from the starting position so
// we can replay them in reverse to return home.
// ---------------------------------------------------------------------------
void doStepPulseAndCount() {
  digitalWrite(stepPin, HIGH);
  delayMicroseconds(pulseWidthUs);
  digitalWrite(stepPin, LOW);
  positionSteps += (directionForward ? 1 : -1);
}


// ---------------------------------------------------------------------------
// returnToStartByCounting — reverse the exact step count to return to start
// After an item is detected we know exactly how many steps we moved forward,
// so we replay them in reverse. This avoids needing a home-position sensor.
// ---------------------------------------------------------------------------
void returnToStartByCounting() {
  if (positionSteps == 0) return;  // Already at start — nothing to do

  Serial.print("Returning to start. Steps to return: ");
  Serial.println(labs(positionSteps));

  // If we moved forward (positive steps), we need to go backward, and vice versa
  bool needForward = (positionSteps < 0);
  setDirection(needForward);

  while (positionSteps != 0) {
    doStepPulseAndCount();
    delayMicroseconds(returnDelayUs);
  }

  Serial.println("Returned to start.");
  setDirection(true);  // Restore default forward direction for the next run
}


// ---------------------------------------------------------------------------
// handleSerialCommands — parse "START" / "STOP" commands from the Pi
// Called every loop iteration; non-blocking (only reads if data is available).
// ---------------------------------------------------------------------------
void handleSerialCommands() {
  if (Serial.available() > 0) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();
    if (cmd == "START") {
      positionSteps = 0;    // Reset step counter at the beginning of every run
      running = true;
      Serial.println("Belt: START");
    } else if (cmd == "STOP") {
      running = false;
      Serial.println("Belt: STOP");
    }
  }
}


// ---------------------------------------------------------------------------
// setup — configure pins and print the startup message
// ---------------------------------------------------------------------------
void setup() {
  Serial.begin(9600);

  pinMode(stepPin,   OUTPUT);
  pinMode(dirPin,    OUTPUT);
  pinMode(buttonPin, INPUT_PULLUP);  // Button pulls to GND when pressed
  pinMode(trigPin,   OUTPUT);
  pinMode(echoPin,   INPUT);

  // Ensure STEP and TRIG are LOW at startup (safe idle state)
  digitalWrite(stepPin, LOW);
  digitalWrite(trigPin, LOW);
  setDirection(true);  // Default to forward

  Serial.println("Ready. Waiting for START command from Raspberry Pi.");
  Serial.println("Button on D5 also works as manual override.");
}


// ---------------------------------------------------------------------------
// loop — non-blocking main loop
// Three concerns are handled independently each iteration:
//   1. Serial command parsing (START / STOP from Pi)
//   2. Button debouncing (manual toggle)
//   3. Motor stepping   (when running == true, at stepDelayUs intervals)
//   4. Sensor sampling  (at sensorIntervalMs intervals while running)
// ---------------------------------------------------------------------------
void loop() {
  handleSerialCommands();
  handleButtonToggle();

  // --- Non-blocking motor stepping ---
  // Only step when the belt is running and enough time has elapsed
  if (running) {
    unsigned long now = micros();
    if (now - lastStepMicros >= stepDelayUs) {
      lastStepMicros = now;
      doStepPulseAndCount();
    }
  }

  // --- Non-blocking ultrasonic sensor check ---
  unsigned long nowMs = millis();
  if (nowMs - lastSensorMs >= sensorIntervalMs) {
    lastSensorMs = nowMs;

    int distance = readDistanceCm();

    // Act only on a valid reading (readDistanceCm returns -1 on timeout)
    if (distance >= 0) {
      if (running && distance < STOP_DISTANCE_CM) {
        running = false;
        Serial.println("STOP: Object detected.");

        // Pause at delivery position, then return home and notify Pi
        delay(pauseAfterDropMs);
        returnToStartByCounting();

        // Notify Raspberry Pi that the delivery cycle is complete
        Serial.println("DONE");
      }
    }
  }
}


// ---------------------------------------------------------------------------
// handleButtonToggle — debounced button read that toggles running state
// Uses a simple 25 ms debounce window: only act when the pin has been stable
// for at least debounceMs milliseconds.
// ---------------------------------------------------------------------------
void handleButtonToggle() {
  bool reading = digitalRead(buttonPin);

  // Reset the debounce timer whenever the raw reading changes
  if (reading != lastRead) {
    lastChangeMs = millis();
    lastRead = reading;
  }

  // The reading is stable if it hasn't changed in debounceMs milliseconds
  if (millis() - lastChangeMs > debounceMs) {
    if (reading != lastStable) {
      lastStable = reading;
      // Act on the falling edge (button pressed = LOW due to INPUT_PULLUP)
      if (lastStable == LOW) {
        running = !running;
        Serial.println(running ? "Belt: START (button)" : "Belt: STOP (button)");
      }
    }
  }
}


// ---------------------------------------------------------------------------
// readDistanceCm — fire the HC-SR04 and return distance in centimetres
// Returns -1 if the echo pulse times out (no object in range or sensor fault).
// echoTimeoutUs prevents pulseIn() from blocking for too long.
// ---------------------------------------------------------------------------
int readDistanceCm() {
  // Send a 10 µs trigger pulse
  digitalWrite(trigPin, LOW);
  delayMicroseconds(2);
  digitalWrite(trigPin, HIGH);
  delayMicroseconds(10);
  digitalWrite(trigPin, LOW);

  // Measure the round-trip echo duration
  unsigned long duration = pulseIn(echoPin, HIGH, echoTimeoutUs);
  if (duration == 0) return -1;  // Timeout — no valid echo received

  // Distance = (duration × speed of sound) / 2
  // Speed of sound ≈ 0.034 cm/µs; divide by 2 for round trip
  return (int)(duration * 0.034 / 2.0);
}

// ===== Stepper (A4988) + HC-SR04 + Serial Control from Raspberry Pi =====
// Half-step microstepping set by wiring on the A4988:
//   MS1=HIGH, MS2=LOW, MS3=LOW
//
// Button: one side GND, other side D5 (INPUT_PULLUP)  [manual override]
// HC-SR04: TRIG D13, ECHO D12
//
// Behavior:
// - Raspberry Pi sends "START\n" over serial to begin the belt
// - If distance < 14 cm while running:
//     1) Stop immediately
//     2) Pause 1 second
//     3) Reverse back to starting position using step counting
//     4) Send "DONE\n" back to Raspberry Pi
// - Button on D5 still works as a manual override

#define dirPin    2
#define stepPin   3
#define buttonPin 5

const int trigPin = 13;
const int echoPin = 12;

// Motor speed: bigger delay = slower
const unsigned int stepDelayUs   = 8000;   // forward speed
const unsigned int returnDelayUs = 8000;   // return speed
const unsigned int pulseWidthUs  = 3;      // STEP high time

// Button debounce
const unsigned long debounceMs = 25;

// Ultrasonic timing
const unsigned long sensorIntervalMs = 100;     // measure ~10x/sec
const unsigned long echoTimeoutUs    = 25000UL; // prevents long blocking

// Stop condition: detected closer than this (cm)
const int STOP_DISTANCE_CM = 14;

// Pause after detection before returning (ms)
const unsigned long pauseAfterDropMs = 1000;

bool running = false;

// Direction tracking (matches what we write to DIR pin)
bool directionForward = true;

// Step-count position relative to "start"
long positionSteps = 0;

// debounce state
bool lastStable = HIGH;
bool lastRead   = HIGH;
unsigned long lastChangeMs = 0;

// step timing
unsigned long lastStepMicros = 0;

// sensor timing
unsigned long lastSensorMs = 0;

void setDirection(bool forward) {
  directionForward = forward;
  digitalWrite(dirPin, directionForward ? HIGH : LOW);
}

void doStepPulseAndCount() {
  digitalWrite(stepPin, HIGH);
  delayMicroseconds(pulseWidthUs);
  digitalWrite(stepPin, LOW);
  positionSteps += (directionForward ? 1 : -1);
}

void returnToStartByCounting() {
  if (positionSteps == 0) return;

  Serial.print("Returning to start. Steps to return: ");
  Serial.println(labs(positionSteps));

  bool needForward = (positionSteps < 0);
  setDirection(needForward);

  while (positionSteps != 0) {
    doStepPulseAndCount();
    delayMicroseconds(returnDelayUs);
  }

  Serial.println("Returned to start.");
  setDirection(true);
}

// Handle "START" / "STOP" commands from Raspberry Pi over serial
void handleSerialCommands() {
  if (Serial.available() > 0) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();
    if (cmd == "START") {
      positionSteps = 0;
      running = true;
      Serial.println("Belt: START");
    } else if (cmd == "STOP") {
      running = false;
      Serial.println("Belt: STOP");
    }
  }
}

void setup() {
  Serial.begin(9600);

  pinMode(stepPin, OUTPUT);
  pinMode(dirPin, OUTPUT);
  pinMode(buttonPin, INPUT_PULLUP);
  pinMode(trigPin, OUTPUT);
  pinMode(echoPin, INPUT);

  digitalWrite(stepPin, LOW);
  digitalWrite(trigPin, LOW);
  setDirection(true);

  Serial.println("Ready. Waiting for START command from Raspberry Pi.");
  Serial.println("Button on D5 also works as manual override.");
}

void loop() {
  handleSerialCommands();
  handleButtonToggle();

  // Motor stepping (non-blocking)
  if (running) {
    unsigned long now = micros();
    if (now - lastStepMicros >= stepDelayUs) {
      lastStepMicros = now;
      doStepPulseAndCount();
    }
  }

  // Sensor check
  unsigned long nowMs = millis();
  if (nowMs - lastSensorMs >= sensorIntervalMs) {
    lastSensorMs = nowMs;

    int distance = readDistanceCm();

    if (distance >= 0) {
      if (running && distance < STOP_DISTANCE_CM) {
        running = false;
        Serial.println("STOP: Object detected.");

        delay(pauseAfterDropMs);
        returnToStartByCounting();

        // Notify Raspberry Pi that delivery is complete
        Serial.println("DONE");
      }
    }
  }
}

void handleButtonToggle() {
  bool reading = digitalRead(buttonPin);

  if (reading != lastRead) {
    lastChangeMs = millis();
    lastRead = reading;
  }

  if (millis() - lastChangeMs > debounceMs) {
    if (reading != lastStable) {
      lastStable = reading;
      if (lastStable == LOW) {
        running = !running;
        Serial.println(running ? "Belt: START (button)" : "Belt: STOP (button)");
      }
    }
  }
}

int readDistanceCm() {
  digitalWrite(trigPin, LOW);
  delayMicroseconds(2);
  digitalWrite(trigPin, HIGH);
  delayMicroseconds(10);
  digitalWrite(trigPin, LOW);

  unsigned long duration = pulseIn(echoPin, HIGH, echoTimeoutUs);
  if (duration == 0) return -1;

  return (int)(duration * 0.034 / 2.0);
}

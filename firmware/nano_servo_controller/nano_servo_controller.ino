#include <Servo.h>

static const int GRIPPER_PIN = 9;   // Nano D9
static const int WRIST_PIN   = 10;  // Nano D10

static const int GRIPPER_MIN_US = 1400;
static const int GRIPPER_MAX_US = 1600;
static const int WRIST_MIN_US   = 1400;
static const int WRIST_MAX_US   = 1600;

Servo gripper;
Servo wrist;
bool gripperAttached = false;
bool wristAttached = false;

void detachAll() {
  if (gripperAttached) {
    gripper.detach();
    gripperAttached = false;
  }
  if (wristAttached) {
    wrist.detach();
    wristAttached = false;
  }
}

bool inRange(const String &name, int us) {
  if (name == "GRIP") return us >= GRIPPER_MIN_US && us <= GRIPPER_MAX_US;
  if (name == "WRIST") return us >= WRIST_MIN_US && us <= WRIST_MAX_US;
  return false;
}

void attachOnly(const String &name) {
  if (name == "GRIP") {
    if (wristAttached) {
      wrist.detach();
      wristAttached = false;
    }
    if (!gripperAttached) {
      gripper.attach(GRIPPER_PIN, GRIPPER_MIN_US, GRIPPER_MAX_US);
      gripperAttached = true;
    }
  } else if (name == "WRIST") {
    if (gripperAttached) {
      gripper.detach();
      gripperAttached = false;
    }
    if (!wristAttached) {
      wrist.attach(WRIST_PIN, WRIST_MIN_US, WRIST_MAX_US);
      wristAttached = true;
    }
  }
}

void setup() {
  Serial.begin(115200);
  detachAll();  // no servo motion on boot
  Serial.println("SEIZO_NANO_SERVO_V1 READY");
}

void loop() {
  if (!Serial.available()) return;

  String line = Serial.readStringUntil('\n');
  line.trim();

  if (line == "HELLO") {
    Serial.println("SEIZO_NANO_SERVO_V1");
    return;
  }

  if (line == "PING") {
    Serial.println("PONG");
    return;
  }

  if (line == "OFF ALL") {
    detachAll();
    Serial.println("OK OFF ALL");
    return;
  }

  int sp = line.indexOf(' ');
  if (sp < 0) {
    Serial.println("ERR BAD_COMMAND");
    return;
  }

  String name = line.substring(0, sp);
  String rest = line.substring(sp + 1);

  if (name == "OFF") {
    if (rest == "GRIP") {
      if (gripperAttached) gripper.detach();
      gripperAttached = false;
      Serial.println("OK OFF GRIP");
    } else if (rest == "WRIST") {
      if (wristAttached) wrist.detach();
      wristAttached = false;
      Serial.println("OK OFF WRIST");
    } else {
      Serial.println("ERR BAD_CHANNEL");
    }
    return;
  }

  int us = rest.toInt();
  if (!inRange(name, us)) {
    Serial.println("ERR OUT_OF_RANGE");
    return;
  }

  attachOnly(name);

  if (name == "GRIP") {
    gripper.writeMicroseconds(us);
    Serial.print("OK GRIP ");
    Serial.println(us);
  } else if (name == "WRIST") {
    wrist.writeMicroseconds(us);
    Serial.print("OK WRIST ");
    Serial.println(us);
  } else {
    Serial.println("ERR BAD_CHANNEL");
  }
}

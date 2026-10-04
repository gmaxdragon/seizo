# Seizo Arduino Nano Servo Controller

## Purpose

Use an Arduino Nano as a local servo coprocessor so the Raspberry Pi sends high-level
servo setpoints over USB while the Nano generates the servo pulses close to the arm.

This does not replace the Arduino Uno + CNC Shield stepper controller.

## Wiring

### Pi to Nano
- Raspberry Pi USB-A -> Arduino Nano USB cable
- Nano logic power comes from USB

### Gripper MG90S
- signal (orange/yellow) -> Nano D9
- red (+V) -> external regulated 5V servo supply +
- brown/black (GND) -> external regulated 5V servo supply GND

### Wrist MG90S
- signal (orange/yellow) -> Nano D10
- red (+V) -> external regulated 5V servo supply +
- brown/black (GND) -> external regulated 5V servo supply GND

### Required common ground
- Nano GND -> external regulated 5V servo supply GND

Do not power the servos from the Nano 5V pin.
Do not connect the external 5V servo rail to Nano 5V while the Nano is USB-powered.

## Firmware

Flash:
`firmware/nano_servo_controller/nano_servo_controller.ino`

Protocol:
- 115200 baud
- `HELLO` -> `SEIZO_NANO_SERVO_V1`
- `PING` -> `PONG`
- `GRIP 1400..1600`
- `WRIST 1400..1600`
- `OFF GRIP`
- `OFF WRIST`
- `OFF ALL`

The firmware boots with both servo outputs detached and allows only one active servo
signal at a time.

## Record & Replay

After the Nano is flashed and wired:

`python3 -u scripts/seizo_record_replay_v21.py --mode manual --action record --servo-backend nano`

For automatic discovery with direct-GPIO fallback:

`--servo-backend auto`

The Nano is auto-detected by serial handshake, not by assuming a fixed /dev/ttyUSB number.

## Detection limitation

A normal 3-wire MG90S has no data/feedback wire. A successful Nano reply proves the
Nano generated the command, not that the servo physically moved. Physical confirmation
must come from camera observation, current sensing, or a feedback-capable servo/sensor.

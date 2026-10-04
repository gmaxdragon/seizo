# ESP32 to Nano Migration V1

Status: planning only. The ESP32 remains installed.

## Goal

Potentially reduce Seizo's controller count by moving suitable ESP32-owned functions to the Arduino Nano, then removing the ESP32 only after the replacement path is proven.

This is not an instruction to remove wiring now.

## Current verified control ownership

- Arduino Uno + CNC Shield + A4988: X/Y/Z steppers.
- Arduino Nano: gripper servo on D9 and wrist servo on D10.
- ESP32: physically installed, but its exact live wire/function ownership is not yet verified in the repository.
- Raspberry Pi: guided UI, cameras, telemetry, planning, and orchestration.

## Current USB identities

Observed in the last published device telemetry:

- Uno: VID:PID 2341:0043, serial 24333313131351101271.
- Nano candidate: VID:PID 1a86:7523.
- ESP32 candidate: VID:PID 10c4:ea60 (CP210x).

The Nano candidate must be selected by USB identity before any Nano handshake is sent. The ESP32 candidate must not receive Nano HELLO/PING or provisioning traffic.

## Why migration cannot be blind

An ESP32 and a classic Nano are not interchangeable controllers.

Before moving any function, verify:

- exact signal wires and pins
- whether the signal is input or output
- 3.3 V versus 5 V logic requirements
- sensor supply voltage
- PWM/timer requirements
- ADC requirements
- interrupt/timing requirements
- UART/I2C/SPI usage
- memory and processing requirements
- whether Wi-Fi or Bluetooth is used
- startup behavior and safe default output state

The Nano is an ATmega328P-class 5 V board with much less memory and compute than an ESP32 and no built-in Wi-Fi/Bluetooth. A function that depends on ESP32 networking, high-speed processing, 3.3 V-only peripherals, or multiple hardware resources may need to stay on the ESP32 or move elsewhere.

## Migration sequence

### Stage 0: identity isolation

Complete in software:

1. Distinguish Uno, Nano, and ESP32 from USB metadata.
2. Never probe ESP32 while looking for Nano.
3. Publish controller inventory with zero serial writes.

### Stage 1: physical ownership map

Requires supervised physical inspection later:

1. Photograph or trace every ESP32 wire.
2. Record ESP32 pin number, destination, voltage, and function.
3. Identify every sensor/actuator currently depending on it.
4. Do not disconnect anything yet.

Deliverable: one authoritative pin/function table.

### Stage 2: capability check

For each ESP32 function, classify:

- safe to move to existing Nano
- safe only with level shifting or extra hardware
- would conflict with Nano D9/D10 servo timing/resources
- should remain on ESP32
- obsolete and can be removed

### Stage 3: one-function shadow migration

Move only one function at a time.

For each function:

1. Add Nano firmware support with safe boot defaults.
2. Test in software and with outputs disconnected when possible.
3. Connect the new Nano path.
4. Validate the function physically under supervision.
5. Keep the ESP32 path available for rollback until the function passes.

### Stage 4: full cutover

Only after every required function has a proven replacement:

1. Save final Nano firmware and pin map in the repo.
2. Run a full hardware check.
3. Verify power, grounds, and startup behavior.
4. Disconnect ESP32 signal wiring.
5. Repeat the full test.
6. Remove the ESP32 only after the robot still passes.

## Non-negotiable rule

Do not flash, repurpose, or remove the ESP32 until its current wiring and function ownership are known.

Controller simplification is useful only if it does not create hidden electrical, timing, or safety regressions.

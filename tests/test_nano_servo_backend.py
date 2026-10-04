import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]

class NanoServoBackendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.nano = (ROOT / "seizo_core/nano_servos.py").read_text()
        cls.firmware = (ROOT / "firmware/nano_servo_controller/nano_servo_controller.ino").read_text()
        cls.rr = (ROOT / "scripts/seizo_record_replay_v21.py").read_text()
        cls.probe = (ROOT / "scripts/seizo_nano_readonly_probe.py").read_text()

    def test_nano_pin_map(self):
        self.assertIn("GRIPPER_PIN = 9", self.firmware)
        self.assertIn("WRIST_PIN   = 10", self.firmware)

    def test_firmware_boots_detached(self):
        self.assertIn("detachAll();  // no servo motion on boot", self.firmware)

    def test_firmware_bounds(self):
        self.assertIn("GRIPPER_MIN_US = 1400", self.firmware)
        self.assertIn("GRIPPER_MAX_US = 1600", self.firmware)
        self.assertIn("WRIST_MIN_US   = 1400", self.firmware)
        self.assertIn("WRIST_MAX_US   = 1600", self.firmware)

    def test_discovery_excludes_grbl_uno(self):
        self.assertIn('UNO_SERIAL = "24333313131351101271"', self.nano)
        self.assertIn('ID_SERIAL_SHORT', self.nano)
        self.assertIn('continue', self.nano)

    def test_discovery_is_usb_scoped_and_excludes_esp32(self):
        block=self.nano.split("def _candidate_ports",1)[1].split("def _open_verified_nano",1)[0]
        self.assertIn("is_expected_nano_props", block)
        self.assertIn("if not is_expected_nano_props(props):", block)
        self.assertIn("continue", block)
        self.assertIn("still-installed", block)

    def test_handshake_detection(self):
        self.assertIn('HANDSHAKE = "SEIZO_NANO_SERVO_V1"', self.nano)
        self.assertIn('ser.write(b"HELLO\\n")', self.nano)

    def test_setup_hint_on_unflashed_nano(self):
        self.assertIn("provision_nano_servo.py", self.nano)

    def test_record_can_continue_without_nano(self):
        self.assertIn("Stepper recording continues", self.rr)
        self.assertIn("if servos is None:", self.rr)
        self.assertNotIn('Type exactly READY', self.rr)
        self.assertNotIn('Type exactly RECORD', self.rr)

    def test_backend_flag(self):
        self.assertIn('--servo-backend', self.rr)
        self.assertIn('choices=["direct", "nano", "auto"]', self.rr)
        self.assertIn("NanoServoController()", self.rr)

    def test_controller_reuses_verified_open_port(self):
        self.assertIn("def _open_verified_nano", self.nano)
        self.assertIn("self.port, self.ser = _open_verified_nano()", self.nano)
        self.assertIn("avoids the old double-reset path", self.nano)

    def test_no_claim_of_position_feedback(self):
        self.assertIn('"actual_position_measured":False', self.nano)

    def test_readonly_probe_never_sends_servo_commands(self):
        self.assertIn('ser.write(b"HELLO\\n")',self.probe)
        self.assertIn('ser.write(b"PING\\n")',self.probe)
        self.assertIn('"servo_output_commands_sent":0',self.probe)
        self.assertNotIn('b"GRIP ',self.probe)
        self.assertNotIn('b"WRIST ',self.probe)
        self.assertNotIn('provision_nano_servo.py',self.probe)


if __name__ == "__main__":
    unittest.main()

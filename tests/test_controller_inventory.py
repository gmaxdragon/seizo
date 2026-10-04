import unittest
from unittest.mock import patch

from seizo_core import controller_inventory as inv
from seizo_core import nano_servos


class ControllerInventoryTests(unittest.TestCase):
    def test_current_usb_roles_are_separate(self):
        uno = {"ID_VENDOR_ID":"2341","ID_MODEL_ID":"0043","ID_SERIAL_SHORT":inv.UNO_SERIAL}
        nano = {"ID_VENDOR_ID":"1A86","ID_MODEL_ID":"7523","ID_SERIAL_SHORT":""}
        esp = {"ID_VENDOR_ID":"10C4","ID_MODEL_ID":"EA60","ID_SERIAL_SHORT":"0001"}
        self.assertEqual(inv.classify_props(uno)["role"], "uno_grbl")
        self.assertEqual(inv.classify_props(nano)["role"], "nano_candidate")
        self.assertEqual(inv.classify_props(esp)["role"], "esp32_candidate")

    def test_nano_filter_never_returns_current_esp32(self):
        ports = ["/dev/ttyUSB0", "/dev/ttyUSB1", "/dev/ttyACM0"]
        props = {
            "/dev/ttyUSB0":{"ID_VENDOR_ID":"1a86","ID_MODEL_ID":"7523"},
            "/dev/ttyUSB1":{"ID_VENDOR_ID":"10c4","ID_MODEL_ID":"ea60","ID_SERIAL_SHORT":"0001"},
            "/dev/ttyACM0":{"ID_VENDOR_ID":"2341","ID_MODEL_ID":"0043","ID_SERIAL_SHORT":inv.UNO_SERIAL},
        }
        with patch.object(nano_servos.glob, "glob", side_effect=[ports[:2], ports[2:]]), \
             patch.object(nano_servos, "_udev", side_effect=lambda p: props[p]):
            self.assertEqual(nano_servos._candidate_ports(), ["/dev/ttyUSB0"])

    def test_inventory_helpers_do_not_open_serial(self):
        source = open("seizo_core/controller_inventory.py", "r", encoding="utf-8").read()
        self.assertNotIn("serial.Serial", source)
        self.assertNotIn("import serial", source)
        self.assertNotIn("RPi.GPIO", source)


if __name__ == "__main__":
    unittest.main()

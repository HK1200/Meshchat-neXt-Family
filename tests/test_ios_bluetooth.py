"""Exercise the native radio boundary without Apple hardware."""
import base64
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / "app/src/main/python/family_ios_bluetooth.py"
spec = importlib.util.spec_from_file_location("family_ios_bluetooth", SOURCE)
bluetooth = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bluetooth)
ADDRESS = "12345678-1234-1234-1234-123456789abc"


class RadioBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.operations = []
        self.events = [{"type": "ready"}]
        self.native = SimpleNamespace(request=self.request)
        self.modules = patch.dict(sys.modules, {"_family_bluetooth": self.native})
        self.modules.start()
        self.addCleanup(self.modules.stop)

    def request(self, text):
        command = json.loads(text)
        self.operations.append(command)
        if command["operation"] == "poll":
            events, self.events = self.events, []
            return json.dumps({"events": events})
        if command["operation"] == "send":
            self.events.extend([
                {"type": "data", "data": base64.b64encode(b"\xc0\x01").decode()},
                {"type": "written"},
            ])
        return '{"ok":true}'

    def test_serial_write_preserves_interleaved_receive_bytes(self):
        radio = bluetooth.Serial("familyble://" + ADDRESS)
        self.assertTrue(radio.is_open)
        self.assertEqual(radio.write(b"\xc0\x00hello\xc0"), 8)
        self.assertEqual(radio.in_waiting, 2)
        self.assertEqual(radio.read(1), b"\xc0")
        self.assertEqual(radio.read(1), b"\x01")
        radio.close()
        radio.close()
        self.assertEqual(sum(c["operation"] == "close" for c in self.operations), 1)

    def test_setup_error_releases_selected_radio(self):
        self.events = [{"type": "error", "detail": "permission denied"}]
        with self.assertRaisesRegex(ConnectionError, "permission denied"):
            bluetooth.Serial("familyble://" + ADDRESS)
        self.assertEqual(self.operations[-1]["operation"], "close")

    def test_disconnect_during_write_fails_without_replay(self):
        radio = bluetooth.Serial("familyble://" + ADDRESS)
        self.native.request = lambda text: json.dumps({"events": [{"type": "closed"}]}) if json.loads(text)["operation"] == "poll" else self.request(text)
        with self.assertRaises(ConnectionError):
            radio.write(b"private packet")
        self.assertFalse(radio.is_open)
        self.assertEqual(sum(c["operation"] == "send" for c in self.operations), 1)
        radio.close()

    def test_radio_identifiers_are_validated(self):
        self.assertEqual(bluetooth.device_id(ADDRESS), ADDRESS.upper())
        with self.assertRaises(ValueError):
            bluetooth.device_id("AA:BB:CC:DD:EE:FF")


if __name__ == "__main__":
    unittest.main()

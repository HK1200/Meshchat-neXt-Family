"""Exercise the native radio boundary without Apple hardware."""
import asyncio
import ast
import runpy
from zipfile import ZipFile
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
        self.assertEqual(bluetooth.last_error(ADDRESS), "permission denied")
        self.events = [{"type": "ready"}]
        radio = bluetooth.Serial("familyble://" + ADDRESS)
        self.assertEqual(bluetooth.last_error(ADDRESS), "")
        radio.close()

    def test_disconnect_during_write_fails_without_replay(self):
        radio = bluetooth.Serial("familyble://" + ADDRESS)
        self.native.request = lambda text: json.dumps({"events": [{"type": "closed"}]}) if json.loads(text)["operation"] == "poll" else self.request(text)
        with self.assertRaises(ConnectionError):
            radio.write(b"private packet")
        self.assertFalse(radio.is_open)
        self.assertEqual(sum(c["operation"] == "send" for c in self.operations), 1)
        radio.close()

    def test_driver_detach_handles_failed_initial_open(self):
        root = SOURCE.parents[4]
        wheel = root / "ios/RuntimeBuild/public/rns-1.5.7-py3-none-any.whl"
        if not wheel.exists():
            self.skipTest("Pinned RNode wheel has not been staged")
        stage = runpy.run_path(str(root / "ios/stage-runtime.py"))
        with ZipFile(wheel) as archive:
            source = stage["tcp_rnode"](archive.read("RNS/Interfaces/RNodeInterface.py").decode())
        driver = next(node for node in ast.parse(source).body if isinstance(node, ast.ClassDef) and node.name == "RNodeInterface")
        detach = next(node for node in driver.body if isinstance(node, ast.FunctionDef) and node.name == "detach")
        namespace = {}
        exec(compile(ast.Module(body=[detach], type_ignores=[]), "RNode-detach", "exec"), namespace)
        radio = SimpleNamespace(serial=None, use_ble=False, use_tcp=False, detached=False,
                                disable_external_framebuffer=lambda: None, setRadioState=lambda value: None, leave=lambda: None)
        namespace["KISS"] = SimpleNamespace(RADIO_STATE_OFF=0)
        namespace["detach"](radio)
        self.assertTrue(radio.detached)

    def test_native_detection_waits_for_pairing_and_reprobes(self):
        root = SOURCE.parents[4]
        wheel = root / "ios/RuntimeBuild/public/rns-1.5.7-py3-none-any.whl"
        if not wheel.exists():self.skipTest("Pinned RNode wheel has not been staged")
        stage = runpy.run_path(str(root / "ios/stage-runtime.py"))
        with ZipFile(wheel) as archive:
            source = stage["tcp_rnode"](archive.read("RNS/Interfaces/RNodeInterface.py").decode())
        driver = next(node for node in ast.parse(source).body if isinstance(node, ast.ClassDef) and node.name == "RNodeInterface")
        configure = next(node for node in driver.body if isinstance(node, ast.FunctionDef) and node.name == "configure_device")
        clock = SimpleNamespace(value=0.0)
        def tick(duration):clock.value += duration
        radio = SimpleNamespace(port="familyble://" + ADDRESS, use_tcp=False, use_ble=False,
                                detached=False, detected=False, serial=SimpleNamespace(is_open=True, close=lambda: self.fail("Pairing was cut off")),
                                platform=0, online=False, readLoop=lambda: None,
                                reset_radio_state=lambda: None, initRadio=lambda: None,
                                validateRadioState=lambda: True)
        probes = []
        def detect():
            probes.append(clock.value)
            radio.detected = len(probes) >= 2
        radio.detect = detect
        namespace = {"sleep": lambda duration: None,
                     "time": SimpleNamespace(time=lambda: clock.value, sleep=tick),
                     "threading": SimpleNamespace(Thread=lambda **options: SimpleNamespace(start=lambda: None)),
                     "KISS": SimpleNamespace(PLATFORM_ESP32=1, PLATFORM_NRF52=2),
                     "RNS": SimpleNamespace(log=lambda *args: None, LOG_VERBOSE=0, LOG_ERROR=0)}
        exec(compile(ast.Module(body=[configure], type_ignores=[]), "RNode-configure", "exec"), namespace)
        namespace["configure_device"](radio)
        self.assertTrue(radio.online)
        self.assertEqual(len(probes), 2)
        self.assertGreaterEqual(clock.value, 3)

    def test_radio_identifiers_are_validated(self):
        self.assertEqual(bluetooth.device_id(ADDRESS), ADDRESS.upper())
        with self.assertRaises(ValueError):
            bluetooth.device_id("AA:BB:CC:DD:EE:FF")


class MeshCoreTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_native_transport_connects_sends_and_dispatches_notifications(self):
        transport_path = SOURCE.parent / "meshchatnext/src/backend/meshcore_transport.py"
        spec = importlib.util.spec_from_file_location("ios_test_meshcore_transport", transport_path)
        transport = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(transport)
        fixture = RadioBoundaryTests()
        fixture.setUp()
        connection = transport.AndroidConnection("ble", ADDRESS, native_factory=bluetooth.NativeSession)
        received = []
        ready = asyncio.Event()
        class Reader:
            async def handle_rx(self, packet):
                received.append(packet)
                ready.set()
        connection.set_reader(Reader())
        try:
            await connection.connect()
            self.assertTrue(connection.is_connected)
            await connection.send(b"private command")
            await asyncio.wait_for(ready.wait(), 2)
            self.assertEqual(received, [b"\xc0\x01"])
            self.assertEqual(sum(c["operation"] == "send" for c in fixture.operations), 1)
        finally:
            await connection.disconnect()
            fixture.doCleanups()
        self.assertFalse(connection.is_connected)


if __name__ == "__main__":
    unittest.main()

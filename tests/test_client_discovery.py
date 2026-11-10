import importlib.util
import json
from pathlib import Path
import signal
import sys
import time
import types
import unittest
from unittest.mock import patch


BACKEND = Path(__file__).resolve().parents[1] / "app/src/main/python/family_backend.py"


class ClientDiscoveryTests(unittest.TestCase):
    address = "ab" * 16
    token = "guardian-session"

    def setUp(self):
        spec = importlib.util.spec_from_file_location("discovery_backend", BACKEND)
        self.backend = importlib.util.module_from_spec(spec)
        original_signal = signal.signal
        try:
            spec.loader.exec_module(self.backend)
        finally:
            signal.signal = original_signal
        self.backend._state = {"setup_complete": True, "contacts": []}
        self.backend._peer = types.SimpleNamespace(online=True)
        self.backend._sessions[self.token] = time.time() + 60

    def find(self, address=None, token=None):
        payload = {"address": address or self.address, "token": token or self.token}
        return json.loads(self.backend.request(json.dumps({"action": "discover_client", "payload": payload})))

    def test_requires_guardian_and_full_lxmf_address(self):
        self.assertFalse(self.find(token="invalid")["ok"])
        self.assertFalse(self.find(address="ab")["ok"])

    def test_lookup_is_bounded_and_does_not_approve_contact(self):
        modules = {
            "RNS": types.SimpleNamespace(
                Destination=types.SimpleNamespace(hash_from_name_and_identity=lambda aspect, identity: bytes.fromhex(self.address)),
                Identity=types.SimpleNamespace(recall_app_data=lambda address: b"verified-name"),
            ),
            "LXMF": types.SimpleNamespace(display_name_from_app_data=lambda data: "Test client"),
        }
        with patch.dict(sys.modules, modules), patch.object(self.backend, "_await_identity", return_value=object()) as wait:
            self.backend._find_client(self.address, self.token)
        self.assertEqual(wait.call_args.kwargs["timeout"], 25)
        self.assertEqual(self.backend._announces[self.address]["name"], "Test client")
        self.assertEqual(self.backend._state["contacts"], [])
        self.assertFalse(self.backend._client_lookup["pending"])

    def test_lookup_rejects_other_reticulum_services(self):
        modules = {
            "RNS": types.SimpleNamespace(
                Destination=types.SimpleNamespace(hash_from_name_and_identity=lambda aspect, identity: b"different-service")
            )
        }
        with patch.dict(sys.modules, modules), patch.object(self.backend, "_await_identity", return_value=object()):
            self.backend._find_client(self.address, self.token)
        self.assertEqual(self.backend._announces, {})
        self.assertIn("different Reticulum service", self.backend._client_lookup["message"])

    def test_lookup_discards_result_after_guardian_locks(self):
        def lock_during_lookup(*args, **kwargs):
            self.backend._sessions.clear()
            return object()

        modules = {
            "RNS": types.SimpleNamespace(
                Destination=types.SimpleNamespace(hash_from_name_and_identity=lambda aspect, identity: bytes.fromhex(self.address))
            )
        }
        with patch.dict(sys.modules, modules), patch.object(self.backend, "_await_identity", side_effect=lock_during_lookup):
            self.backend._find_client(self.address, self.token)
        self.assertEqual(self.backend._announces, {})
        self.assertEqual(self.backend._client_lookup, {"pending": False, "message": ""})

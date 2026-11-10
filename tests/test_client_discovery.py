import importlib.util
import json
from pathlib import Path
import signal
import sys
import threading
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


    def test_text_and_voice_announce_at_startup_hourly_and_after_reconnect(self):
        text, voice = [], []
        peer = self.backend._peer
        self.backend._state.update(peer={"enabled": True}, voiceEnabled=True)
        self.backend._destination = types.SimpleNamespace(announce=lambda attached_interface: text.append(attached_interface))
        self.backend._voice = types.SimpleNamespace(phone=types.SimpleNamespace(announce=lambda attached_interface: voice.append(attached_interface)))
        rns = types.SimpleNamespace(Transport=types.SimpleNamespace(interfaces=[peer]))
        with patch.dict(sys.modules, {"RNS": rns}), patch.object(self.backend.time, "monotonic", side_effect=[0, 3599, 3600, 3601, 3602, 7200]):
            self.backend._announce_available_routes()
            self.assertEqual((text, voice), ([peer], [peer]))
            self.backend._announce_available_routes()
            self.assertEqual((len(text), len(voice)), (1, 1))
            self.backend._announce_available_routes()
            self.assertEqual((len(text), len(voice)), (2, 2))
            peer.family_connection_epoch = 1
            self.backend._announce_available_routes()
            self.assertEqual((len(text), len(voice)), (3, 3))
            self.backend._state["voiceEnabled"] = False
            self.backend._announce_available_routes()
            self.backend._announce_available_routes()
            self.assertEqual((len(text), len(voice)), (3, 3))

    def test_renaming_reannounces_text_and_voice_without_waiting_an_hour(self):
        text, voice = [], []
        peer = self.backend._peer
        state = self.backend._state
        state.update(peer={"enabled": True}, voiceEnabled=True, device_name="neXt Family")
        endpoint = types.SimpleNamespace(
            display_name=state["device_name"], announce=lambda attached_interface: text.append(endpoint.display_name)
        )
        self.backend._destination = endpoint
        self.backend._voice = types.SimpleNamespace(
            phone=types.SimpleNamespace(announce=lambda attached_interface: voice.append(state["device_name"]))
        )
        rns = types.SimpleNamespace(Transport=types.SimpleNamespace(interfaces=[peer]))
        def snapshot():
            self.backend._announce_available_routes()
            return {}
        with (
            patch.dict(sys.modules, {"RNS": rns}),
            patch.object(self.backend, "_save"),
            patch.object(self.backend, "_snapshot", side_effect=snapshot),
        ):
            self.backend._announce_available_routes()
            payload = {"name": "Renamed Family", "token": self.token}
            reply = self.backend.request(json.dumps({"action": "device_name", "payload": payload}))
            self.assertTrue(json.loads(reply)["ok"], reply)
            self.backend._announce_available_routes()
        self.assertEqual(text, ["neXt Family", "Renamed Family"])
        self.assertEqual(voice, text)

    def test_deferred_voice_announces_when_it_becomes_available(self):
        text, voice = [], []
        peer = self.backend._peer
        self.backend._state.update(peer={"enabled": True}, voiceEnabled=True)
        self.backend._destination = types.SimpleNamespace(announce=lambda attached_interface: text.append(attached_interface))
        self.backend._voice = types.SimpleNamespace(phone=types.SimpleNamespace(announce=lambda attached_interface: voice.append(attached_interface)))
        self.backend._voice_deferred = True
        rns = types.SimpleNamespace(Transport=types.SimpleNamespace(interfaces=[peer]))
        with patch.dict(sys.modules, {"RNS": rns}), patch.object(self.backend.time, "monotonic", return_value=0):
            self.backend._announce_available_routes()
            self.assertEqual((text, voice), ([peer], []))
            self.backend._voice_deferred = False
            self.backend._announce_available_routes()
            self.assertEqual((text, voice), ([peer], [peer]))


class MeshCoreDiscoveryTests(unittest.TestCase):
    def test_key_only_advert_keeps_unapproved_client_visible(self):
        spec = importlib.util.spec_from_file_location("discovery_meshcore", BACKEND.with_name("family_meshcore.py"))
        meshcore = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(meshcore)
        with (
            patch.dict(sys.modules, {"family_meshcore_rooms": types.SimpleNamespace(MeshCoreRooms=lambda owner: None)}),
            patch.object(meshcore.threading.Thread, "start"),
        ):
            radio = meshcore.FamilyMeshCore({"contacts": []}, threading.RLock(), lambda: None)
        self.addCleanup(radio.loop.close)
        client, room, cached_client = "ab" * 32, "cd" * 32, "ef" * 32
        radio.contacts[cached_client] = {"type": 1, "adv_name": "Radio contact"}
        for payload in (
            {"public_key": client, "type": 1, "adv_name": "Unapproved client"},
            {"public_key": client},
            {"public_key": cached_client},
            {"public_key": room, "type": 3, "adv_name": "Room server"},
        ):
            radio._announce(types.SimpleNamespace(payload=payload))
        self.assertEqual(
            {row["address"]: row["name"] for row in radio.snapshot()["clientAnnounces"]},
            {client: "Unapproved client", cached_client: "Radio contact"},
        )
        self.assertEqual(radio.allowed(), {})

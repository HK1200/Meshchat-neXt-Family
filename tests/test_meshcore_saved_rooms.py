import sys
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app/src/main/python"))
from family_meshcore_rooms import MeshCoreRooms


class SavedMeshCoreRoomsTest(unittest.TestCase):
    def test_saved_room_logs_in_without_opening_and_rejoins_after_disconnect(self):
        owner, saved, unsaved = "11" * 32, "22" * 32, "33" * 32
        manager = SimpleNamespace(
            owner=owner,
            connected=True,
            revision=1,
            lock=threading.RLock(),
            save=lambda: None,
            state={
                "meshcore": {"publicKey": owner, "receive": True},
                "rooms": [
                    {"id": 1, "name": "Saved", "key": saved, "service": "meshcore"},
                    {"id": 2, "name": "Unsaved", "key": unsaved, "service": "meshcore"},
                ],
                "meshcore_room_keys": {"1": "encrypted-fixture"},
            },
        )
        rooms = MeshCoreRooms(manager)
        requests = []

        def queue(room, runtime):
            requests.append(room["id"])
            runtime.update(joining=False, attempted=True, joined=True, owner=owner)

        with patch.object(rooms, "_queue_join", side_effect=queue):
            rooms.tick()
            rooms.close_view()
            rooms.tick()
            self.assertIsNone(rooms.active)
            self.assertTrue(rooms.snapshot()["roomRuntime"]["1"]["joined"])
            self.assertEqual(requests, [1])
            rooms.disconnected()
            manager.connected = False
            rooms.tick()
            self.assertEqual(requests, [1])
            manager.connected = True
            manager.revision += 1
            rooms.tick()
            self.assertEqual(requests, [1, 1])
            self.assertFalse(rooms.snapshot()["roomRuntime"]["2"]["joined"])

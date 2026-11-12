import asyncio
import sys
import time
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

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


class MeshCoreRoomPostClockTest(unittest.IsolatedAsyncioTestCase):
    async def test_post_keeps_login_order_and_falls_back_to_host_time_for_skew(self):
        owner, peer = "11" * 32, "22" * 32
        now = int(time.time())
        sent_type = object()
        for offset, expected in [(5, now + 6), (120, now), (None, now)]:
            with self.subTest(offset=offset):
                get_time = AsyncMock(
                    return_value={"time": now + offset} if offset is not None else {},
                    side_effect=ConnectionError("Clock unavailable") if offset is None else None,
                )
                send_msg = AsyncMock(return_value=SimpleNamespace(
                    type=sent_type, payload={"expected_ack": b"test", "suggested_timeout": 1000}
                ))
                record = {"id": "post", "owner": owner, "delivery": "sending"}
                manager = SimpleNamespace(
                    owner=owner, connected=True, revision=1, lock=threading.RLock(),
                    save=lambda: None, _acks={},
                    state={
                        "meshcore": {"publicKey": owner, "receive": True},
                        "rooms": [{"id": 1, "key": peer, "service": "meshcore"}],
                        "meshcore_room_messages": {"1": [record]},
                    },
                    session=SimpleNamespace(
                        _lock=asyncio.Lock(), _payload=lambda payload: payload,
                        _client=SimpleNamespace(commands=SimpleNamespace(
                            get_time=get_time, send_msg=send_msg
                        )),
                    ),
                )
                meshcore = SimpleNamespace(EventType=SimpleNamespace(MSG_SENT=sent_type))
                with patch.dict(sys.modules, {"meshcore": meshcore}), patch(
                    "family_meshcore_rooms.time.time", return_value=now
                ):
                    await MeshCoreRooms(manager)._post(1, "post", "hello", 1, owner)
                send_msg.assert_awaited_once_with(peer, "hello", timestamp=expected, attempt=0)
                self.assertEqual(record["delivery"], "accepted")

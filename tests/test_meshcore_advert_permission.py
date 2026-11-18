import asyncio
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app/src/main/python'))
from family_meshcore import FamilyMeshCore


def manager():
    value = FamilyMeshCore.__new__(FamilyMeshCore)
    value.lock = threading.RLock()
    value.owner = 'ab' * 32
    value.revision = 7
    value.connected = True
    value.state = {'meshcore': {'enabled': True, 'publicKey': value.owner}}
    value._advert_write = None
    return value


@pytest.mark.parametrize('payload', [b'\x07', b'\x07\x01', b'\x07\x02'])
def test_adverts_without_explicit_guardian_operation_never_reach_radio(payload):
    radio = manager()
    write = Mock()
    with pytest.raises(ValueError, match='Guardian advert'):
        radio._guard_send(7, payload, write)
    write.assert_not_called()


@pytest.mark.parametrize('flood', [False, True])
def test_authorized_operation_sends_exact_sdk_packet_and_clears_permit(flood):
    async def run():
        radio = manager()
        writes = []
        authorized = Mock()
        async def send_advert(*, flood):
            packet = b'\x07\x01' if flood else b'\x07'
            radio._guard_send(7, packet, lambda: writes.append(packet))
            return {}
        radio.session = SimpleNamespace(_lock=asyncio.Lock(), _payload=lambda event: event,
            _client=SimpleNamespace(commands=SimpleNamespace(send_advert=send_advert)))
        await radio._advertise(flood, authorized, 7, radio.owner)
        assert writes == [b'\x07\x01' if flood else b'\x07']
        assert authorized.call_count == 2
        assert radio._advert_write is None
    asyncio.run(run())


def test_locking_guardian_before_handoff_cancels_advert_and_clears_permit():
    async def run():
        radio = manager()
        write = Mock()
        authorize = Mock(side_effect=[None, ValueError('Guardian locked')])
        async def send_advert(*, flood):
            radio._guard_send(7, b'\x07', write)
        radio.session = SimpleNamespace(_lock=asyncio.Lock(), _payload=lambda event: event,
            _client=SimpleNamespace(commands=SimpleNamespace(send_advert=send_advert)))
        with pytest.raises(ValueError, match='Guardian locked'):
            await radio._advertise(False, authorize, 7, radio.owner)
        write.assert_not_called()
        assert radio._advert_write is None
    asyncio.run(run())


def test_stale_companion_is_rejected_before_sdk_command():
    async def run():
        radio = manager()
        radio.session = SimpleNamespace(_lock=asyncio.Lock())
        with pytest.raises(ValueError, match='Companion identity changed'):
            await radio._advertise(False, lambda: None, 6, radio.owner)
        assert radio._advert_write is None
    asyncio.run(run())

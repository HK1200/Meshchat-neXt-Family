import copy
from pathlib import Path
import sys
import threading

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app/src/main/python'))
from family_room_names import RoomNames


@pytest.mark.parametrize('service,participant', [('meshcore', 'ab'*4), ('reticulum', 'ab'*16)])
def test_names_stay_in_the_room_and_never_approve_private_contact_or_location(service, participant):
    state = {'contacts': [], 'location_policy': {'recipients': [], 'until': 0}, 'rooms': [
        {'id': 1, 'service': service, 'key': 'server-one'},
        {'id': 2, 'service': service, 'key': 'server-two'}]}
    before = copy.deepcopy(state)
    names = RoomNames(state, threading.RLock(), lambda: None)
    names.set(1, participant, 'Known room speaker')
    source = {'rooms': state['rooms'], 'roomRuntime': {
        '1': {'messages': [{'seq': 1, 'participantId': participant, 'nick': 'Reported'}]},
        '2': {'messages': [{'seq': 2, 'participantId': participant, 'nick': 'Reported'}]}}}
    result = names.decorate(copy.deepcopy(source))
    assert result['roomRuntime']['1']['messages'][0]['nick'] == 'Known room speaker'
    assert result['roomRuntime']['2']['messages'][0]['nick'] == 'Reported'
    assert state['contacts'] == before['contacts']
    assert state['location_policy'] == before['location_policy']
    assert source['roomRuntime']['1']['messages'][0]['nick'] == 'Reported'
    names.set(1, participant, '')
    assert names.decorate(copy.deepcopy(source))['roomRuntime']['1']['messages'][0]['nick'] == 'Reported'


def test_invalid_names_and_unapproved_rooms_are_rejected():
    names = RoomNames({'rooms': [{'id': 1, 'key': 'server', 'service': 'meshcore'}]}, threading.RLock(), lambda: None)
    for room, participant, label in [(2, 'ab'*4, 'Name'), (1, 'invalid', 'Name'), (1, 'ab'*4, 'bad\nname')]:
        with pytest.raises(ValueError):
            names.set(room, participant, label)

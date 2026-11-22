"""Real mobile telemetry fields, sender attribution and silent map updates."""
from pathlib import Path
from types import SimpleNamespace
import base64
import sys
import time
import pytest
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'ios/NextRuntimeProbe'),str(ROOT/'app/src/main/python')]
import LXMF
from telemetry_runtime import TelemetryRuntime,incoming_fields,outbound,validated
from meshchatnext.src.backend.telemetry_utils import Telemeter


def fix():
    return {'latitude':48.75,'longitude':-122.48,'accuracy':10,'last_update':int(time.time())}


def test_outgoing_location_uses_standard_wire_format_and_preserves_attachment_policy():
    photo={'image':{'image_bytes':'private fixture'}}
    attachments,fields=outbound({**photo,'telemetry':{'location':fix()}})
    assert attachments==photo and set(fields)=={LXMF.FIELD_TELEMETRY}
    clean=Telemeter.from_packed(fields[LXMF.FIELD_TELEMETRY])
    assert clean['location']['latitude']==48.75 and clean['location']['longitude']==-122.48


@pytest.mark.parametrize('value',[{'location':{'latitude':True,'longitude':0}}, {'location':{'latitude':float('nan'),'longitude':0}}, {'location':{'latitude':91,'longitude':0}}, {'location':{**fix(),'last_update':time.time()+3600}}, {'battery':{'charge_percent':101,'charging':False}}, {'time':{'utc':True},'location':fix()}, {'unknown':123}])
def test_invalid_sensor_data_cannot_be_packed(value):
    with pytest.raises(ValueError):validated(value)


def test_saved_legacy_telemetry_stays_private_and_does_not_make_chat_unread(tmp_path):
    from loopback_probe import ConversationHistory,record
    peer='02'*16;history=ConversationHistory(tmp_path/'history.sqlite3')
    message=SimpleNamespace(fields={},hash=b't'*32,source_hash=bytes.fromhex(peer),destination_hash=b'o'*16,
        timestamp=time.time(),method=LXMF.LXMessage.DIRECT,content_as_string=lambda:'!NFLOC1:old synthetic location')
    row=record(message,'received');row.pop('is_private_telemetry');history.save(peer,row)
    assert history.page(peer,{})==[] and not history.has_conversation(peer)
    assert history.conversation_entries()=={} and not history.summary(peer)['is_unread']
    assert history.notification_candidates()==[]
    assert history.message(row['hash']) is not None  # Preserved, not deleted.
    history.close()

"""Call/PCM ownership, native permission gating and route-local voice scheduling."""
import asyncio
from collections import deque
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace

import pytest
import RNS

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ios/NextRuntimeProbe"))
from voice_runtime import ReticulumVoice, PCMClient, address


class Native:
    def __init__(self): self.requests=[]; self.events=deque(); self.allow=True
    def __call__(self, request):
        self.requests.append(request.copy())
        if request["op"] == "dial" and not self.allow: raise RuntimeError("Native call permission denied")
        if request["op"] == "poll":
            result=list(self.events); self.events.clear(); return {"ok":True,"events":result}
        return {"ok":True}


class Engine:
    def __init__(self, identity, config, callbacks, loop):
        self.closed=False;self.callbacks=callbacks;self.frames=[];self.clients=[];self.announces=[]
        self.bridge=SimpleNamespace(attach_client=self.attach)
        phone=SimpleNamespace(destination=SimpleNamespace(hash=b"v"*16),active_call=None,call_status=3)
        async def initiate(peer, timeout_seconds):
            phone.active_call=object();phone.call_status=2
        def announce(**value):self.announces.append(value)
        self.manager=SimpleNamespace(telephone=phone,initiation_status=None,
            set_call_policy=lambda **kwargs: setattr(self, "call_policy", kwargs),
            resolve_audio_profile_id=lambda:64,resolve_call_mode_id=lambda:0,
            initiate=initiate,announce=announce,mute_transmit=lambda:None,unmute_transmit=lambda:None,
            get_active_mode_id=lambda:1,is_half_duplex=lambda:False,ptt_active=False,
            mute_receive=lambda:None,unmute_receive=lambda:None,
            apply_preferred_profile=lambda value:value,apply_preferred_mode=lambda value:value)
    def attach(self,client):self.clients.append(client);return True
    def dispose(self):self.closed=True;self.manager.telephone=None
    def push(self,data,processed):self.frames.append((data,processed))


def fixture():
    database=sqlite3.connect(":memory:")
    native=Native();identity=RNS.Identity()
    voice=ReticulumVoice(database,identity,lambda:{},lambda:[],lambda:"Private test",
                         native=native,engine_factory=Engine)
    return voice,native,database


def connect(voice,identity=None):
    identity=identity or RNS.Identity()
    peer=RNS.Destination.hash_from_name_and_identity("lxst.telephony",identity.hash).hex()
    return identity,peer


@pytest.mark.parametrize("value",[None,12,"", "a"*31,"g"*32,"../"+"a"*29,True])
def test_invalid_voice_addresses_are_rejected(value):
    with pytest.raises(ValueError):address(value)


def test_new_install_is_off_and_does_not_start_a_telephone_or_microphone():
    async def run():
        voice,native,db=fixture()
        try:
            assert not voice.snapshot()["enabled"] and voice.engine is None
            assert [row["op"] for row in native.requests]==["open"]
            with pytest.raises(ValueError,match="Enable"):await voice.dial("a"*32)
            await voice.tick()
            assert [row["op"] for row in native.requests]==["open","poll"]
        finally:await voice.close();db.close()
    asyncio.run(run())


def test_native_permission_must_succeed_before_dialing_the_reticulum_transport():
    async def run():
        voice,native,db=fixture()
        try:
            await voice.configure(True)
            _,peer=connect(voice)
            await voice.dial(peer)
            call=voice.call
            assert call.phase=="preparing" and voice.task is None
            native.events.append({"operation":"dial","call_id":call.id})
            await voice.tick();await asyncio.sleep(0)
            assert call.phase=="finding" and voice.engine.manager.telephone.active_call is not None
        finally:await voice.close();db.close()
    asyncio.run(run())


def test_denied_native_dial_does_not_keep_a_pending_call():
    async def run():
        voice,native,db=fixture()
        try:
            await voice.configure(True);native.allow=False
            with pytest.raises(RuntimeError,match="permission"):await voice.dial("a"*32)
            assert voice.call is None and voice.task is None
            assert voice.engine.manager.telephone.active_call is None
        finally:await voice.close();db.close()
    asyncio.run(run())


def test_exact_call_ids_guard_controls_and_late_transport_callbacks():
    async def run():
        voice,native,db=fixture()
        try:
            await voice.configure(True)
            identity,peer=connect(voice)
            await voice.dial(peer);old=voice.call;old_engine=voice.engine
            with pytest.raises(ValueError,match="changed"):voice.control("hangup",{"call_id":"b"*32})
            await voice.end(old.id)
            assert old_engine.closed and voice.engine is not old_engine
            await voice.dial(peer);new=voice.call
            voice.transport_event(old_engine,"ended",identity)
            voice.transport_event(old_engine,"established",identity)
            assert voice.call is new and new.phase=="preparing"
            native.events.append({"operation":"hangup","call_id":old.id})
            await voice.tick()
            assert voice.call is new and voice.ending is None
        finally:await voice.close();db.close()
    asyncio.run(run())


def test_old_audio_client_cannot_inject_pcm_into_a_new_call():
    async def run():
        voice,native,db=fixture()
        try:
            await voice.configure(True)
            identity,peer=connect(voice)
            await voice.dial(peer)
            voice.transport_event(voice.engine,"established",identity)
            old_client=voice.client;old_id=voice.call.id
            await voice.end(old_id)
            await voice.dial(peer)
            voice.transport_event(voice.engine,"established",identity)
            await old_client.send_bytes(b"\x01\x00"*4000)
            assert voice.pull(voice.call.id)==b""
            voice.push(old_id,b"\x01\x00"*960,True)
            assert voice.engine.frames==[]
            await voice.client.send_bytes(b"\x01\x00"*2880)
            assert len(voice.pull(voice.call.id))==1920
        finally:await voice.close();db.close()
    asyncio.run(run())


def test_pcm_limits_muting_and_reconfiguration_healing():
    async def run():
        voice,native,db=fixture()
        try:
            await voice.configure(True)
            identity,peer=connect(voice);await voice.dial(peer)
            voice.transport_event(voice.engine,"established",identity)
            identifier=voice.call.id;engine=voice.engine
            for bad in [b"a",b"a"*11522,"not bytes",b""]:
                voice.push(identifier,bad,True)
            assert engine.frames==[]
            voice.push(identifier,b"\x00\x00"*960,True)
            assert engine.frames==[(b"\x00\x00"*960,True)]
            voice.call.muted=True
            voice.push(identifier,b"\x00\x00"*960,True)
            assert len(engine.frames)==1
            before=len(engine.clients);await voice.tick()
            assert len(engine.clients)>before
            await voice.client.send_bytes(b"\x01\x00"*96000)
            assert len(voice.received)<=48000
            assert len(voice.pull(identifier))==1920
            voice.call.id="0"*32
            assert voice.pull("0"*32)==b""
            voice.call.id=identifier
        finally:await voice.close();db.close()
    asyncio.run(run())


def test_voice_announces_only_live_routes_at_start_reconnect_and_hourly():
    async def run():
        voice,native,db=fixture();now=[0.]
        live=SimpleNamespace(online=True,detached=False,family_connection_epoch=1)
        offline=SimpleNamespace(online=False,detached=False)
        voice.interfaces=lambda:[live,offline];voice.clock=lambda:now[0]
        try:
            await voice.configure(True)
            assert await voice.announce_due()==1
            assert await voice.announce_due()==0
            now[0]=3599;assert await voice.announce_due()==0
            now[0]=3600;assert await voice.announce_due()==1
            live.family_connection_epoch=2;assert await voice.announce_due()==1
            live.detached=True;assert await voice.announce_due(force=True)==0
            assert len(voice.engine.announces)==3
            assert all(row["display_name"]=="Private test" for row in voice.engine.announces)
        finally:await voice.close();db.close()
    asyncio.run(run())


def test_saved_voice_configuration_survives_service_recreation():
    async def run():
        voice,native,db=fixture()
        await voice.configure(True);await voice.close()
        replacement=ReticulumVoice(db,RNS.Identity(),lambda:{},lambda:[],lambda:"Private test",
                                  native=Native(),engine_factory=Engine)
        try:
            assert replacement.snapshot()["enabled"]
            await replacement.start()
            assert replacement.engine is not None
        finally:await replacement.close();db.close()
    asyncio.run(run())


def test_lxmf_contact_hint_resolves_to_the_authenticated_voice_identity():
    async def run():
        voice,native,db=fixture()
        identity,peer=connect(voice)
        lxmf=RNS.Destination.hash_from_name_and_identity("lxmf.delivery",identity.hash).hex()
        voice.contacts=lambda:{lxmf:{"name":"Saved contact"}}
        try:
            await voice.configure(True);await voice.dial(lxmf)
            voice.transport_event(voice.engine,"established",identity)
            assert voice.call.peer==peer and voice.call.identity==identity.hash.hex()
            assert voice.snapshot()["active_call"]["remote_identity_name"]=="Saved contact"
        finally:await voice.close();db.close()
    asyncio.run(run())


def test_receive_mute_discards_buffered_and_new_audio_but_keeps_microphone():
    async def run():
        voice,native,db=fixture()
        try:
            await voice.configure(True);identity,peer=connect(voice);await voice.dial(peer)
            voice.transport_event(voice.engine,"established",identity)
            identifier=voice.call.id
            await voice.client.send_bytes(b"\x01\x00"*2880)
            await voice.set_receive_muted({"call_id":identifier},True)
            await voice.client.send_bytes(b"\x01\x00"*2880)
            assert voice.pull(identifier)==b"" and not voice.received
            voice.push(identifier,b"\x01\x00"*960,True)
            assert len(voice.engine.frames)==1
            await voice.set_receive_muted({"call_id":identifier},False)
            await voice.client.send_bytes(b"\x01\x00"*2880)
            assert len(voice.pull(identifier))==1920
        finally:await voice.close();db.close()
    asyncio.run(run())


def test_bad_saved_call_configuration_cannot_break_messaging_or_reenable_voice():
    async def run():
        db=sqlite3.connect(":memory:")
        db.execute("CREATE TABLE next_voice_settings (key TEXT PRIMARY KEY,value TEXT)")
        db.execute("INSERT INTO next_voice_settings VALUES ('enabled','\"bad\"')")
        native=Native()
        voice=ReticulumVoice(db,RNS.Identity(),lambda:{},lambda:[],lambda:"Private test",native=native,engine_factory=Engine)
        try:
            assert not voice.snapshot()["enabled"] and "could not be read" in voice.error
            assert db.execute("SELECT value FROM next_voice_settings").fetchone()[0]=='"bad"'
        finally:await voice.close();db.close()
    asyncio.run(run())


def test_late_ringing_cannot_demote_an_established_call():
    async def run():
        voice,native,db=fixture()
        try:
            await voice.configure(True);identity,peer=connect(voice);await voice.dial(peer)
            voice.transport_event(voice.engine,"established",identity)
            voice.transport_event(voice.engine,"ringing",identity)
            assert voice.call.phase=="connected" and voice.pcm_ready
        finally:await voice.close();db.close()
    asyncio.run(run())


def test_http_voice_routes_enforce_exact_call_ids_and_strict_inputs():
    from aiohttp.test_utils import TestClient,TestServer
    from aiohttp import web
    async def run():
        voice,native,db=fixture();app=web.Application();voice.register(app.router)
        async with TestClient(TestServer(app)) as client:
            try:
                response=await client.get('/api/v1/preview/reticulum-calling')
                assert response.status==200 and not (await response.json())["enabled"]
                response=await client.post('/api/v1/preview/reticulum-calling',json={"enabled":"yes"})
                assert response.status==400 and not voice.snapshot()["enabled"]
                response=await client.post('/api/v1/preview/reticulum-calling',json={"enabled":True})
                assert response.status==200
                response=await client.post('/api/v1/telephone/call/'+'a'*32,json={})
                assert response.status==200
                identifier=voice.call.id
                before=len(native.requests)
                response=await client.post('/api/v1/telephone/hangup',json={"call_id":"b"*32})
                assert response.status==400 and len(native.requests)==before
                response=await client.post('/api/v1/telephone/mute-transmit',json={"call_id":identifier})
                assert response.status==200 and native.requests[-1]["value"] is True
                response=await client.post('/api/v1/telephone/unmute-transmit',json={"call_id":identifier})
                assert response.status==200 and native.requests[-1]["value"] is False
                response=await client.post('/api/v1/telephone/hangup',json={"call_id":identifier})
                assert response.status==200 and native.requests[-1]["op"]=="hangup"
            finally:await voice.close();db.close()
    asyncio.run(run())


def test_real_engine_installs_live_caller_policy_and_preserves_restrictions():
    async def run():
        voice,native,db=fixture()
        caller=RNS.Identity()
        lxmf=RNS.Destination.hash_from_name_and_identity("lxmf.delivery",caller.hash).hex()
        try:
            assert not voice.caller_allowed(caller.hash)
            await voice.configure(True)
            allowed=voice.engine.call_policy["allowed_fn"]
            assert not allowed(caller.hash)  # Matches desktop neXt on a fresh install.
            voice.set_call_policy({"telephone_allow_calls_from_contacts_only":False})
            assert allowed(caller.hash)
            voice.set_call_policy({"telephone_allow_calls_from_contacts_only":True})
            assert not allowed(caller.hash)
            voice.contacts=lambda:{lxmf:{"name":"Known caller"}}
            voice.refresh_call_contacts()
            assert allowed(caller.hash)
            assert await asyncio.to_thread(allowed, caller.hash)
            voice.set_call_policy({"do_not_disturb_enabled":True})
            assert not allowed(caller.hash)
            voice.set_call_policy({"do_not_disturb_enabled":False,"blocked_callers":[lxmf]})
            assert not allowed(caller.hash)
            voice.set_call_policy({"blocked_callers":[]})
            assert allowed(caller.hash)
            voice.contacts=lambda:{}
            voice.refresh_call_contacts()
            assert not allowed(caller.hash)
            for malformed in ({"do_not_disturb_enabled":"false"},{"blocked_callers":["bad"]},{"unknown":False}):
                with pytest.raises(ValueError):voice.set_call_policy(malformed)
            assert not allowed(caller.hash) and not allowed(b"bad")
        finally:await voice.close();db.close()
    asyncio.run(run())


def test_dial_failure_remains_visible_after_the_engine_recovers():
    async def run():
        voice,native,db=fixture()
        try:
            await voice.configure(True)
            async def fail(*args,**kwargs):raise RuntimeError("Private transport refused the call")
            voice.engine.manager.initiate=fail
            await voice.dial("a"*32)
            native.events.append({"operation":"dial","call_id":voice.call.id})
            await voice.tick();await asyncio.sleep(0)
            if voice.ending:await voice.ending
            assert voice.call is None and voice.engine is not None
            assert "transport refused" in voice.snapshot()["error"]
            await voice.dial("b"*32)
            assert not voice.snapshot()["error"]
        finally:await voice.close();db.close()
    asyncio.run(run())


def test_call_history_records_once_and_uses_authenticated_identity_for_contact_name():
    async def run():
        voice,native,db=fixture()
        caller,peer=connect(voice)
        lxmf=RNS.Destination.hash_from_name_and_identity("lxmf.delivery",caller.hash).hex()
        try:
            await voice.configure(True)
            voice.transport_event(voice.engine,"ringing",caller)
            call=voice.call
            await voice.end(call.id)
            voice.record_call(call)
            rows=voice.call_history({})["call_history"]
            assert len(rows)==1 and rows[0]["status"]=="Missed"
            assert voice.snapshot()["missed_calls_unread_count"]==1
            voice.contacts=lambda:{lxmf:{"name":"Renamed contact"}}
            rows=voice.call_history({})["call_history"]
            assert rows[0]["remote_identity_name"]=="Renamed contact"
            assert rows[0]["remote_destination_hash"]==lxmf and rows[0]["is_contact"]
            await voice.dial(peer)
            voice.transport_event(voice.engine,"established",caller)
            await voice.end(voice.call.id)
            rows=voice.call_history({})["call_history"]
            assert len(rows)==2 and rows[0]["status"]=="Completed"
            assert rows[0]["duration_seconds"]>=0 and not rows[0]["is_incoming"]
            assert voice.call_history({"search":"no match"})=={"call_history":[]}
            assert len(voice.call_history({"limit":"1","offset":"1"})["call_history"])==1
            for query in ({"limit":"bad"},{"limit":-1},{"limit":251},{"offset":-1},{"search":"a"*513}):
                with pytest.raises(ValueError):voice.call_history(query)
        finally:await voice.close();db.close()
    asyncio.run(run())


def test_call_history_routes_mark_missed_viewed_and_clear_only_voice_history():
    from aiohttp import web
    from aiohttp.test_utils import TestClient,TestServer
    async def run():
        voice,native,db=fixture()
        try:
            await voice.configure(True)
            caller,peer=connect(voice)
            voice.transport_event(voice.engine,"ringing",caller)
            await voice.end(voice.call.id)
            app=web.Application();voice.register(app.router)
            async with TestClient(TestServer(app)) as client:
                response=await client.get("/api/v1/telephone/history")
                assert response.status==200 and len((await response.json())["call_history"])==1
                response=await client.post("/api/v1/telephone/missed-calls/mark-viewed")
                assert response.status==200 and voice.missed_count()==0
                response=await client.get("/api/v1/telephone/history?offset=-1")
                assert response.status==400
                response=await client.delete("/api/v1/telephone/history")
                assert response.status==200 and not voice.call_history({})["call_history"]
                assert db.execute("SELECT COUNT(*) FROM next_voice_settings").fetchone()[0]>0
        finally:await voice.close();db.close()
    asyncio.run(run())


def test_history_storage_failure_never_keeps_the_microphone_or_call_alive():
    async def run():
        voice,native,db=fixture()
        try:
            await voice.configure(True)
            caller,peer=connect(voice)
            await voice.dial(peer)
            voice.transport_event(voice.engine,"established",caller)
            old=voice.engine
            db.execute("CREATE TRIGGER reject_voice_history BEFORE INSERT ON next_voice_calls BEGIN SELECT RAISE(FAIL, 'synthetic disk failure'); END")
            await voice.end(voice.call.id)
            assert old.closed and voice.call is None and voice.engine is not old
            assert not voice.pcm_ready
            assert "history could not be saved" in voice.snapshot()["error"]
            assert not voice.snapshot()["is_busy"]
        finally:await voice.close();db.close()
    asyncio.run(run())


def test_incoming_caller_name_uses_link_identity_without_requiring_an_announce():
    async def run():
        voice,native,db=fixture()
        caller,peer=connect(voice)
        lxmf=RNS.Destination.hash_from_name_and_identity("lxmf.delivery",caller.hash).hex()
        voice.contacts=lambda:{lxmf:{"name":"Known LXMF contact"}}
        try:
            await voice.configure(True)
            voice.transport_event(voice.engine,"ringing",caller)
            assert voice.call.name=="Known LXMF contact"
            assert voice.snapshot()["active_call"]["remote_destination_hash"]==lxmf
            incoming=[row for row in native.requests if row.get("state")=="incoming"]
            assert incoming[0]["name"]=="Known LXMF contact"
        finally:await voice.close();db.close()
    asyncio.run(run())


def test_native_speaker_requires_a_connected_exact_call_and_real_boolean():
    async def run():
        voice,native,db=fixture()
        try:
            await voice.configure(True)
            caller,peer=connect(voice);await voice.dial(peer)
            identifier=voice.call.id
            with pytest.raises(ValueError,match="Connect"):voice.control("speaker",{"call_id":identifier,"value":True})
            voice.transport_event(voice.engine,"established",caller)
            for payload in ({"call_id":"f"*32,"value":True},{"call_id":identifier,"value":1},{"call_id":identifier,"value":"true"}):
                before=len(native.requests)
                with pytest.raises(ValueError):voice.control("speaker",payload)
                assert len(native.requests)==before
            voice.control("speaker",{"call_id":identifier,"value":True})
            assert native.requests[-1]["op"]=="speaker" and native.requests[-1]["value"] is True
            voice.control("speaker",{"call_id":identifier,"value":False})
            assert native.requests[-1]["value"] is False
        finally:await voice.close();db.close()
    asyncio.run(run())


def test_explicit_saved_open_caller_policy_is_preserved_instead_of_reset_to_default():
    async def run():
        voice,native,db=fixture()
        voice.set_call_policy({"telephone_allow_calls_from_contacts_only":False})
        await voice.close()
        restored=ReticulumVoice(db,RNS.Identity(),lambda:{},lambda:[],lambda:"Private test",
                               native=Native(),engine_factory=Engine)
        try:
            assert restored.call_policy["telephone_allow_calls_from_contacts_only"] is False
            assert not restored.snapshot()["enabled"]
        finally:await restored.close();db.close()
    asyncio.run(run())


def test_global_message_policy_uses_initial_contacts_without_starting_voice():
    async def run():
        db=sqlite3.connect(":memory:")
        db.execute("CREATE TABLE next_voice_settings (key TEXT PRIMARY KEY,value TEXT)")
        db.execute("INSERT INTO next_voice_settings VALUES ('block_all_from_strangers','true')")
        native=Native();known="a"*32
        voice=ReticulumVoice(db,RNS.Identity(),lambda:{known:{"name":"Private contact"}},lambda:[],lambda:"Private test",
                             native=native,engine_factory=Engine)
        try:
            assert voice.engine is None and not voice.config.telephone_enabled.get()
            assert voice.message_allowed(known)
            assert not voice.message_allowed("b"*32)
            for invalid in (None,True,"", "g"*32):assert not voice.message_allowed(invalid)
            voice.set_call_policy({"block_all_from_strangers":False})
            assert voice.message_allowed("b"*32)
            assert [row["op"] for row in native.requests]==["open"]
        finally:await voice.close();db.close()
    asyncio.run(run())


def test_capture_status_uses_only_recent_audio_from_the_current_call():
    async def run():
        voice,native,db=fixture()
        now=[100.0]
        voice.clock=lambda:now[0]
        original_native=voice.native
        waiting="Microphone captured. Waiting for Reticulum to send audio."
        voice.native=lambda request: ({"ok":True,"capture_status":waiting}
            if request["op"]=="capabilities" else original_native(request))
        try:
            await voice.configure(True)
            identity,peer=connect(voice)
            await voice.dial(peer)
            voice.transport_event(voice.engine,"established",identity)
            call_id=voice.call.id
            assert voice.snapshot()["capture_status"]==waiting
            voice.push(call_id,b"\x01\x00"*960,True)
            assert voice.snapshot()["capture_status"]=="Microphone audio is flowing."
            voice.call.muted=True
            assert voice.snapshot()["capture_status"]=="Microphone muted."
            voice.call.muted=False
            now[0]+=3
            assert voice.snapshot()["capture_status"]==waiting
            voice.push(call_id,b"\x01\x00"*960,True)
            assert voice.snapshot()["capture_status"]=="Microphone audio is flowing."
            await voice.end(call_id)
            await voice.dial(peer)
            voice.transport_event(voice.engine,"established",identity)
            voice.push(call_id,b"\x01\x00"*960,True)
            assert voice.snapshot()["capture_status"]==waiting
        finally:await voice.close();db.close()
    asyncio.run(run())


def test_call_hint_lifecycle_runs_only_after_native_dial_acceptance_and_before_end():
    async def run():
        voice, native, db = fixture(); events = []
        voice.on_call_start = lambda call: events.append(("start", call.id, call.phase))
        voice.on_call_end = lambda call: events.append(("end", call.id, call.phase))
        try:
            await voice.configure(True)
            native.allow = False
            with pytest.raises(RuntimeError): await voice.dial("a" * 32)
            assert events == []
            native.allow = True
            await voice.dial("a" * 32)
            identity = voice.call.id
            assert events == [("start", identity, "preparing")]
            await voice.end(identity)
            assert events[-1] == ("end", identity, "ending")
        finally: await voice.close(); db.close()
    asyncio.run(run())


def test_optional_hint_failure_cannot_break_an_ordinary_call():
    async def run():
        voice, native, db = fixture()
        def failed(_): raise RuntimeError("Private fixture only")
        voice.on_call_start = voice.on_call_end = failed
        try:
            await voice.configure(True)
            await voice.dial("a" * 32)
            identity = voice.call.id
            await voice.end(identity)
            assert voice.call is None
        finally: await voice.close(); db.close()
    asyncio.run(run())


def test_native_policy_pause_must_finish_before_any_policy_or_enabled_value_changes():
    async def run():
        voice, native, db = fixture()
        attempts = []
        def pause():
            attempts.append(True)
            raise ValueError("Consent could not be made durable")
        try:
            voice.before_policy_change = pause
            with pytest.raises(ValueError): voice.set_call_policy({"do_not_disturb_enabled": True})
            assert voice.call_policy["do_not_disturb_enabled"] is False
            with pytest.raises(ValueError): await voice.configure(True)
            assert voice.config.telephone_enabled.get() is False
            assert attempts == [True, True]
        finally: await voice.close(); db.close()
    asyncio.run(run())


def test_unchanged_call_permissions_do_not_pause_call_alerts():
    async def run():
        voice, native, db = fixture(); attempts = []
        voice.before_policy_change = lambda: attempts.append(True)
        try:
            voice.set_call_policy({"do_not_disturb_enabled": False})
            await voice.configure(False)
            assert attempts == []
        finally: await voice.close(); db.close()
    asyncio.run(run())

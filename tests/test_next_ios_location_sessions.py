"""Location consent, lifetime, throttling and late-send revocation without GPS."""
import asyncio
from pathlib import Path
import sqlite3
import sys

import pytest
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'ios/NextRuntimeProbe'),str(ROOT/'app/src/main/python')]
from location_sessions import LocationSessions


class Fixture:
    def __init__(self,path=':memory:'):
        self.now=1000.;self.monotonic=100.;self.requests=[];self.delivered=[]
        self.contacts={'rns:one':{'name':'One','service':'reticulum','online':True}}
        self.fix={'latitude':48.,'longitude':-122.,'accuracy':10,'last_update':self.now}
        self.can_submit=True;self.native_generation=1
        self.db=sqlite3.connect(path)
        self.manager=LocationSessions(self.db,self.catalog,self.native,self.transmit,
                                      clock=lambda:self.now,monotonic=lambda:self.monotonic)
    async def catalog(self):return dict(self.contacts)
    async def native(self,request):
        self.requests.append(request)
        return {'ok':True,'can_submit':self.can_submit,'generation':self.native_generation,'foreground':True,'fix':dict(self.fix)}
    async def transmit(self,target,fix,guard):
        if not await guard():return False
        self.delivered.append((target,fix));return True
    async def tick(self):
        await self.manager.tick()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
    def advance(self,seconds,moved=False):
        self.now+=seconds;self.monotonic+=seconds;self.fix['last_update']=self.now
        if moved:self.fix['latitude']+=.001
    async def close(self):await self.manager.close();self.db.close()


def test_nothing_requests_gps_until_explicit_start_and_saved_resume_is_not_automatic(tmp_path):
    async def run():
        f=Fixture(tmp_path/'state.sqlite3')
        try:
            assert f.requests==[] and not (await f.manager.snapshot())['active']
            await f.manager.tick();assert f.requests==[]
            await f.manager.start(['rns:one'],'ongoing',background=True)
            await f.manager.close()
            assert f.db.execute('select count(*) from next_location_sessions').fetchone()[0]==1
            f.requests.clear()
            restored=LocationSessions(f.db,f.catalog,f.native,f.transmit,clock=lambda:f.now,monotonic=lambda:f.monotonic)
            assert f.requests==[]
            assert (await restored.snapshot())['paused'] is True
            await restored.tick();assert f.requests==[]
            await restored.resume();assert f.requests[-1]['op']=='resume'
            assert (await restored.snapshot())['active'] is True
            await restored.close()
        finally:await f.close()
    asyncio.run(run())


@pytest.mark.parametrize('targets,duration,background',[
    ([], '15',False),([{}],'15',False),([12],'15',False),(['rns:one'],'unknown',False),
    (['rns:one'],{},False),(['rns:one','rns:one'],'15',False),(['rns:one'],'15','yes'),
    (['missing'],'15',False),
])
def test_invalid_or_removed_recipients_do_not_request_gps(targets,duration,background):
    async def run():
        f=Fixture()
        try:
            with pytest.raises(ValueError):await f.manager.start(targets,duration,background=background)
            assert not f.requests and not f.manager.sessions
        finally:await f.close()
    asyncio.run(run())


def test_moving_and_stopped_intervals_and_offline_targets():
    async def run():
        f=Fixture()
        try:
            await f.manager.start(['rns:one'],'15')
            await f.tick();assert len(f.delivered)==1
            f.advance(59,True);await f.tick();assert len(f.delivered)==1
            f.advance(1);await f.tick();assert len(f.delivered)==2
            f.advance(299);await f.tick();assert len(f.delivered)==2
            f.advance(1);await f.tick();assert len(f.delivered)==3
            f.contacts['rns:one']['online']=False
            f.advance(300,True);await f.tick();assert len(f.delivered)==3
        finally:await f.close()
    asyncio.run(run())


@pytest.mark.parametrize('action',['stop','remove','expire','background','replace'])
def test_waiting_path_cannot_send_after_consent_or_native_generation_changes(action):
    async def run():
        f=Fixture();entered=asyncio.Event();release=asyncio.Event()
        async def delayed(target,fix,guard):
            entered.set()
            try:await release.wait()
            except asyncio.CancelledError:pass  # An uninterruptible transport worker still has to check consent.
            if await guard():f.delivered.append((target,fix));return True
            return False
        f.manager.transmit=delayed
        try:
            await f.manager.start(['rns:one'],'15')
            await f.manager.tick();await entered.wait()
            if action=='stop':await f.manager.stop()
            elif action=='remove':f.contacts.clear();await f.manager.tick()
            elif action=='expire':f.advance(901);await f.manager.tick()
            elif action=='background':f.can_submit=False;f.native_generation+=1
            else:await f.manager.start(['rns:one'],'60')
            release.set();await asyncio.sleep(0);await asyncio.sleep(0)
            assert f.delivered==[]
        finally:release.set();await f.close()
    asyncio.run(run())


def test_stop_revokes_gps_and_delivery_even_if_storage_is_unwritable():
    async def run():
        f=Fixture()
        try:
            await f.manager.start(['rns:one'],'15',background=True)
            f.manager._persist=lambda _:(_ for _ in ()).throw(OSError('storage unavailable'))
            with pytest.raises(OSError):await f.manager.stop()
            assert f.requests[-1]['op']=='stop' and not f.manager.armed and not f.manager.sessions
            await f.tick();assert f.delivered==[]
        finally:await f.close()
    asyncio.run(run())


def test_snapshot_never_includes_catalog_secrets_or_location_coordinates():
    async def run():
        f=Fixture()
        try:
            f.contacts['rns:one']['password']='private fixture'
            snapshot=await f.manager.snapshot()
            assert snapshot['recipients']==[{'id':'rns:one','name':'One','service':'reticulum','online':True}]
            assert 'latitude' not in str(snapshot) and 'private fixture' not in str(snapshot)
        finally:await f.close()
    asyncio.run(run())


def test_stop_arriving_before_start_cannot_be_undone_by_the_late_request():
    async def run():
        f=Fixture();request_id='a'*32
        try:
            await f.manager.stop('rns:one',request_id=request_id)
            f.requests.clear()
            with pytest.raises(ValueError,match='cancelled'):
                await f.manager.start(['rns:one'],'15',request_id=request_id,consent_epoch=0)
            assert f.requests==[] and not f.manager.sessions
        finally:await f.close()
    asyncio.run(run())


def test_old_stop_cannot_end_a_newer_explicit_sharing_request():
    async def run():
        f=Fixture()
        try:
            await f.manager.start(['rns:one'],'15',request_id='a'*32)
            await f.manager.start(['rns:one'],'60',request_id='b'*32)
            await f.manager.stop('rns:one',request_id='a'*32)
            assert f.manager.sessions['rns:one'].revision=='b'*32
            assert (await f.manager.snapshot())['active']
        finally:await f.close()
    asyncio.run(run())


def test_stop_all_invalidates_requests_prepared_under_the_old_controls():
    async def run():
        f=Fixture()
        try:
            old=(await f.manager.snapshot())['consent_epoch']
            await f.manager.stop()
            f.requests.clear()
            with pytest.raises(ValueError,match='controls changed'):
                await f.manager.start(['rns:one'],'15',request_id='a'*32,consent_epoch=old)
            assert f.requests==[]
        finally:await f.close()
    asyncio.run(run())


@pytest.mark.parametrize('boundary',['catalog','native'])
def test_revocation_during_guard_await_is_checked_again(boundary):
    async def run():
        f=Fixture()
        try:
            await f.manager.start(['rns:one'],'15')
            revision=f.manager.sessions['rns:one'].revision
            original=f.catalog if boundary=='catalog' else f.native
            async def interrupted(*args):
                result=await original(*args)
                # Revocation can race an awaited lookup or native bridge.
                f.manager.sessions.clear();f.manager.armed=False
                return result
            if boundary=='catalog':f.manager.catalog=interrupted
            else:f.manager.native=interrupted
            assert not await f.manager._guard('rns:one',revision,1)
        finally:await f.close()
    asyncio.run(run())


def test_a_path_wait_cannot_transmit_an_expired_fix():
    async def run():
        f=Fixture();entered=asyncio.Event();release=asyncio.Event()
        async def delayed(target,fix,guard):
            entered.set();await release.wait()
            if await guard():f.delivered.append(fix);return True
            return False
        f.manager.transmit=delayed
        try:
            await f.manager.start(['rns:one'],'ongoing')
            await f.manager.tick();await entered.wait()
            f.advance(121)
            release.set();await asyncio.sleep(0);await asyncio.sleep(0)
            assert f.delivered==[]
        finally:release.set();await f.close()
    asyncio.run(run())


@pytest.mark.parametrize('duration,deadline',[('15',1000),('15',1901),('ongoing',1900),('60',True),('60',float('nan'))])
def test_invalid_expiry_does_not_start_gps(duration,deadline):
    async def run():
        f=Fixture()
        try:
            with pytest.raises(ValueError):await f.manager.start(['rns:one'],duration,deadline=deadline)
            assert f.requests==[]
        finally:await f.close()
    asyncio.run(run())


def test_saved_deadline_is_not_extended_by_a_delayed_start_or_restart():
    async def run():
        f=Fixture()
        try:
            await f.manager.start(['rns:one'],'15',deadline=1800)
            assert f.manager.sessions['rns:one'].until==1800
            assert f.requests[0]['until']==1800
            expected=f.manager.sessions['rns:one'].grant_id('rns:one')
            assert f.requests[0]['revisions']==[expected]
            await f.manager.close()
            assert f.requests[-1]['op']=='suspend'
        finally:await f.close()
    asyncio.run(run())


def test_cancelled_ongoing_request_does_not_revive_after_an_hour():
    async def run():
        f=Fixture()
        try:
            await f.manager.stop('rns:one', request_id='a'*32)
            f.advance(3601)
            with pytest.raises(ValueError,match='cancelled'):
                await f.manager.start(['rns:one'],'ongoing',request_id='a'*32,consent_epoch=0)
        finally:await f.close()
    asyncio.run(run())


def test_native_consent_is_separate_for_each_recipient_in_one_start_request():
    async def run():
        f=Fixture()
        f.contacts['rns:two']={'name':'Two','service':'reticulum','online':True}
        try:
            await f.manager.start(['rns:one','rns:two'],'15',request_id='a'*32)
            approved=set(f.requests[-1]['revisions'])
            assert len(approved)==2
            await f.manager.stop('rns:one',request_id='a'*32)
            retained=set(f.requests[-1]['revisions'])
            assert len(retained)==1 and retained < approved
        finally:await f.close()
    asyncio.run(run())


def test_new_start_never_silently_resumes_other_saved_recipients_after_restart():
    async def run():
        f=Fixture()
        f.contacts['rns:two']={'name':'Two','service':'reticulum','online':True}
        restored=None
        try:
            await f.manager.start(['rns:one'],'15')
            await f.manager.close()
            restored=LocationSessions(f.db,f.catalog,f.native,f.transmit,clock=lambda:f.now,monotonic=lambda:f.monotonic)
            assert (await restored.snapshot())['paused']
            await restored.start(['rns:two'],'15')
            assert set(restored.sessions)=={'rns:two'}
        finally:
            if restored:await restored.close()
            await f.close()
    asyncio.run(run())


def test_enabling_locked_sharing_for_one_recipient_does_not_enable_another():
    async def run():
        f=Fixture();f.contacts['rns:two']={'name':'Two','service':'reticulum','online':True}
        original=f.native
        async def locked(request):return {**await original(request),'foreground':False}
        f.manager.native=locked
        try:
            await f.manager.start(['rns:one'],'ongoing',background=False)
            await f.manager.start(['rns:two'],'15',background=True)
            await f.tick()
            assert [target['name'] for target,_ in f.delivered]==['Two']
        finally:await f.close()
    asyncio.run(run())


def test_native_background_expiry_is_not_extended_by_an_ongoing_foreground_session():
    async def run():
        f=Fixture();f.contacts['rns:two']={'name':'Two','service':'reticulum','online':True}
        try:
            await f.manager.start(['rns:one'],'ongoing',background=False)
            await f.manager.start(['rns:two'],'15',background=True)
            assert f.requests[-1]['background'] is True and f.requests[-1]['until']==1900
        finally:await f.close()
    asyncio.run(run())


def test_native_grant_binds_recipient_expiry_and_background_permission():
    from location_sessions import Session
    base=Session(1900,'15','a'*32,False)
    assert base.grant_id('rns:one')==Session(1900.0,'15','a'*32,False).grant_id('rns:one')
    assert len({base.grant_id('rns:one'),base.grant_id('rns:two'),
                Session(1901,'15','a'*32,False).grant_id('rns:one'),
                Session(1900,'15','a'*32,True).grant_id('rns:one')})==4


def test_old_session_schema_does_not_inherit_the_global_background_preference(tmp_path):
    path=tmp_path/'legacy.sqlite3'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE next_location_sessions(target TEXT PRIMARY KEY, until REAL, duration TEXT, revision TEXT)')
        db.execute('INSERT INTO next_location_sessions VALUES(?,?,?,?)',('rns:one',1900,'15','a'*32))
        db.execute('CREATE TABLE next_location_options(key TEXT PRIMARY KEY, value TEXT)')
        db.execute('INSERT INTO next_location_options VALUES(?,?)',('background','true'))
    async def run():
        f=Fixture(path)
        try:
            assert f.requests==[]
            state=await f.manager.snapshot()
            assert state['paused'] and state['sessions'][0]['background'] is False
            await f.manager.resume()
            assert f.requests[-1]['background'] is False
        finally:await f.close()
    asyncio.run(run())


def test_a_late_start_cannot_override_the_newer_recipient_selection():
    async def run():
        f=Fixture();f.contacts['rns:two']={'name':'Two','service':'reticulum','online':True}
        try:
            await f.manager.start(['rns:two'],'15',request_id='b'*32,consent_epoch=0)
            with pytest.raises(ValueError,match='controls changed'):
                await f.manager.start(['rns:one'],'ongoing',background=True,request_id='a'*32,consent_epoch=0)
            assert set(f.manager.sessions)=={'rns:two'}
        finally:await f.close()
    asyncio.run(run())


def test_identical_start_retry_is_idempotent_and_does_not_extend_expiry():
    async def run():
        f=Fixture()
        try:
            await f.manager.start(['rns:one'],'15',request_id='a'*32,consent_epoch=0,deadline=1900)
            calls=len(f.requests);f.advance(10)
            await f.manager.start(['rns:one'],'15',request_id='a'*32,consent_epoch=0,deadline=1900)
            assert len(f.requests)==calls and f.manager.sessions['rns:one'].until==1900
        finally:await f.close()
    asyncio.run(run())


def test_idle_tick_and_summary_do_not_repeatedly_read_the_contact_database():
    async def run():
        f=Fixture()
        async def forbidden():raise AssertionError('An idle UI refresh must not scan contact history')
        f.manager.catalog=forbidden
        try:
            await f.manager.tick()
            state=await f.manager.snapshot(include_recipients=False)
            assert not state['active'] and state['sessions']==[] and state['recipients']==[] and f.requests==[]
        finally:await f.close()
    asyncio.run(run())

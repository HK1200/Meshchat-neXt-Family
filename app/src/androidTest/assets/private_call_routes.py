"""Actual Android package/crypto checks. No radio, network, or real profile."""
def verify_private_call_routes(parent):
    import json, socket, tempfile, threading, uuid
    from pathlib import Path
    class ForbiddenSocket(socket.socket):
        def __new__(cls, *args, **kwargs):
            raise AssertionError('The isolated device test cannot open a socket')
    socket.socket = ForbiddenSocket
    import family_backend as backend
    import RNS
    from family_call_alerts import FamilyCallHints, route_for
    from family_call_wake import destination_hash, voice_hash, signed_bytes, valid_shape
    assert backend._root is None, 'Abort if an existing app profile has initialized'
    own, peer = RNS.Identity(), RNS.Identity()
    address = destination_hash('lxmf.delivery', peer.get_public_key())
    voice = voice_hash(peer.get_public_key())
    def request(action, **payload):
        return json.loads(backend.request(json.dumps({'action': action, 'payload': payload})))
    operations = []
    accepted = threading.Event()
    def mock_provider(route, operation, raw):
        hint = json.loads(raw)
        assert valid_shape(hint)
        assert own.validate(bytes.fromhex(hint['signature']), signed_bytes(hint, route.audience, cancel=operation == 'call-cancel'))
        assert hint['recipient'] == voice
        assert 'Private fixture' not in raw.decode()
        operations.append(operation)
        if operation == 'call-alert': accepted.set()
        return 204
    with tempfile.TemporaryDirectory(prefix='private-call-routes-', dir=parent) as directory:
        backend._root = Path(directory)
        backend._state = {'setup_complete': True, 'voiceEnabled': True,
            'password_salt': '12' * 16,
            'contacts': [{'id': 7, 'name': 'Private fixture', 'identityPublicKey': peer.get_public_key().hex(),
                'addresses': {'lxmf': address, 'lxst': voice}}]}
        backend._state['password_hash'] = backend._password('temporary-device-fixture')
        handle = None
        try:
            entry = {'provider': 'https://example.invalid', 'audience': 'private-device-calls'}
            assert not request('call_alert_route_set', contactId=7, route=entry)['ok']
            assert 'callAlertRoutes' not in backend._state
            assert not request('unlock', password='incorrect-fixture')['ok']
            reply = request('unlock', password='temporary-device-fixture')
            assert reply['ok']; token = reply['token']
            assert request('call_alert_route_set', token=token, contactId=7, route=entry)['ok']
            assert request('call_alert_route_get', token=token, contactId=7)['callAlertRoute'] == entry
            saved = (Path(directory) / 'state.json').read_bytes()
            assert not request('call_alert_route_set', token=token, contactId=7, route={**entry, 'provider': 'http://example.invalid'})['ok']
            assert (Path(directory) / 'state.json').read_bytes() == saved
            sender = FamilyCallHints(own, backend._state, backend._lock, sender=mock_provider)
            handle = sender.start(7, uuid.uuid4().hex, voice)
            assert handle is not None and accepted.wait(5)
            handle.cancel(); handle.thread.join(timeout=6)
            assert not handle.thread.is_alive() and operations == ['call-alert', 'call-cancel']
            assert request('call_alert_route_set', token=token, contactId=7, route=None)['ok']
            assert route_for(backend._state, 7) is None
            assert sender.start(7, uuid.uuid4().hex, voice) is None
            assert request('lock', token=token)['ok']
            assert not request('call_alert_route_get', token=token, contactId=7)['ok']
        finally:
            if handle:
                handle.cancel(); handle.thread.join(timeout=6)
            backend._root = None; backend._state = None; backend._sessions.clear()
    return json.dumps({'guardian_authentication': True, 'private_route_crud': True,
        'invalid_route_preserved_saved_bytes': True, 'actual_android_signature_validated': True,
        'ordered_wake_and_cancel': True, 'removed_route_sends_nothing': True,
        'network_and_radio_forbidden': True, 'fixture_removed': True})

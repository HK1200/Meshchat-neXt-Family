"""Native iOS adapters for neXt's existing SIP account/connection service.

Importing or constructing an adapter never opens a socket or starts SIP.
The native transport owns CallKit/audio and binds controls to its exact call ID.
"""
import asyncio
import contextlib
from collections import deque
import json
import re
import uuid


def native_request(payload):
    raw = json.dumps(payload, allow_nan=False)
    if len(raw.encode()) > 16 * 1024:
        raise ValueError('SIP request exceeds the native limit')
    try:
        from _next_sip import request
    except ImportError:
        raise RuntimeError('Native SIP calling is not enabled in this build') from None
    reply = json.loads(request(raw))
    if not isinstance(reply, dict) or reply.get('ok') is not True:
        raise ConnectionError('Native SIP operation could not be completed')
    return reply


def password_request(payload):
    from _next_credentials import request
    raw = json.dumps(dict(payload, domain='sip'), allow_nan=False)
    if len(raw.encode()) > 16 * 1024:
        raise ValueError('SIP credential request exceeds the native limit')
    reply = json.loads(request(raw))
    if not isinstance(reply, dict) or reply.get('ok') is not True:
        raise ConnectionError('Secure SIP password storage is unavailable')
    return reply


class IOSPasswords:
    def __init__(self, request=password_request):
        self.request = request

    def _call(self, operation, account_id, **values):
        account = str(uuid.UUID(account_id))
        try:
            return self.request(dict(op=operation, account=account, **values))
        except (ConnectionError, RuntimeError):
            raise ValueError('Secure SIP password storage is unavailable') from None

    def save(self, account_id, password):
        if (not isinstance(password, str) or not password or '\0' in password
                or len(password.encode()) > 256):
            raise ValueError('Use a SIP password of at most 256 UTF-8 bytes without NUL')
        self._call('password-save', account_id, password=password)

    def load(self, account_id, *, interactive=True):
        # After-first-unlock Keychain reads do not display a UI unlock prompt.
        value = self._call('password-load', account_id).get('value')
        if (not isinstance(value, str) or not value or '\0' in value
                or len(value.encode()) > 256):
            raise ValueError('Secure SIP password is unavailable')
        return value

    def remove(self, account_id):
        self._call('password-remove', account_id)


def networks(request=native_request):
    rows = request({'op': 'networks'}).get('networks')
    if not isinstance(rows, list) or len(rows) > 1:
        raise ValueError('The current iOS default route is unavailable')
    result = []
    for row in rows:
        if (not isinstance(row, dict) or row.get('kind') not in ('wifi', 'mobile', 'ethernet')
                or not isinstance(row.get('interface'), str)
                or not re.fullmatch('[A-Za-z0-9_.:-]{1,80}', row['interface'])
                or not isinstance(row.get('address'), str) or len(row['address']) > 128):
            raise ValueError('Invalid native SIP route')
        result.append({key: row[key] for key in ('interface', 'address', 'kind')})
    # Report only the OS's current default route. An unselected cellular link
    # must not be presented as a usable route while the engine is on Wi-Fi.
    return result


class IOSSIPEngine:
    """Transport contract; calling stays unavailable until the native engine is linked."""
    CALL_STATES = {'incoming', 'calling', 'ringing', 'progress', 'connected', 'ended', 'muted', 'audio_error', 'command_failed'}
    STATES = CALL_STATES | {'ready', 'registering', 'registered', 'registration_failed', 'engine_failed', 'stopped', 'stats'}

    def __init__(self, executable=None, *, interface=None, local_address=None,
                 request=native_request, poll_interval=0.1):
        self.request = request
        self.interface = interface
        self.poll_interval = poll_interval
        self.session = uuid.uuid4().hex
        self.on_event = None
        self._running = False
        self._opened = False
        self._task = None
        self._call_id = ''
        self._retired = deque(maxlen=256)
        self._received_stop = False
        self._lifecycle = asyncio.Lock()
        self._commands = asyncio.Lock()

    @property
    def running(self):
        return self._running

    async def _request(self, operation, **values):
        return await asyncio.to_thread(self.request, dict(op=operation, session=self.session, **values))

    async def launch(self):
        async with self._lifecycle:
            if self._running:
                return
            await self._request('open', interface=self.interface)
            self._received_stop = False
            self._opened = True
            self._running = True
            self._task = asyncio.create_task(self._pump())

    def _retire_call(self):
        if self._call_id:
            self._retired.append(self._call_id)
            self._call_id = ''

    def deliver(self, event):
        if self._received_stop:
            return
        if (not isinstance(event, dict) or not isinstance(event.get('state'), str)
                or event['state'] not in self.STATES):
            return
        state = event['state']
        native_id = event.get('native_id', '')
        peer = event.get('peer', '')
        if not isinstance(peer, str) or len(peer) > 512:
            return
        if state in self.CALL_STATES:
            if not isinstance(native_id, str) or not re.fullmatch('[A-Za-z0-9_.-]{1,80}', native_id):
                return
            if native_id in self._retired:
                return
            if state in ('incoming', 'calling') and not self._call_id:
                self._call_id = native_id
            if self._call_id != native_id:
                return
            if state == 'ended':
                self._retire_call()
        if state == 'stopped':
            self._running = False
            self._received_stop = True
            self._retire_call()
        if self.on_event:
            self.on_event({key: value for key, value in event.items() if key in {
                'state', 'peer', 'code', 'sent', 'received', 'lost_rx', 'jitter_ms', 'rtt_ms'
            }})

    async def _pump(self):
        try:
            while self._running:
                async with self._commands:
                    reply = await self._request('poll')
                    events = reply.get('events', [])
                    if not isinstance(events, list) or len(events) > 256:
                        raise ConnectionError('Invalid native SIP events')
                    for event in events:
                        self.deliver(event)
                    if reply.get('closed'):
                        self.deliver({'state': 'stopped', 'peer': ''})
                await asyncio.sleep(self.poll_interval)
        except asyncio.CancelledError:
            raise
        except Exception:
            self.deliver({'state': 'stopped', 'peer': '', 'code': -1})

    async def command(self, op, **fields):
        async with self._commands:
            return await self._command(op, **fields)

    async def _command(self, op, **fields):
        if not self._running:
            raise ValueError('Connect SIP before using call controls')
        if op not in {'start', 'dial', 'answer', 'hangup', 'mute', 'hold', 'digit', 'speaker', 'stats'}:
            raise ValueError('Unsupported native SIP action')
        values = dict(fields)
        if op == 'dial':
            if self._call_id:
                raise ValueError('End the current SIP call first')
            peer = values.get('peer')
            if not isinstance(peer, str) or not peer.startswith('sip:') or len(peer) > 320 or any(c in peer for c in '\r\n\0<>" '):
                raise ValueError('Invalid SIP address')
            self._call_id = uuid.uuid4().hex
            values['call_id'] = self._call_id
        elif op not in {'start', 'stats'}:
            if not self._call_id:
                raise ValueError('The SIP call has ended')
            values['call_id'] = self._call_id
        if op in {'mute', 'hold', 'speaker'} and type(values.get('value')) is not bool:
            raise ValueError('Invalid SIP call option')
        if op == 'digit' and values.get('digit') not in tuple('0123456789*#ABCD'):
            raise ValueError('Invalid SIP keypad digit')
        try:
            return await self._request(op, **values)
        except BaseException:
            if op == 'dial':
                self._retire_call()
            raise

    async def _finish_close(self, reply):
        deadline = asyncio.get_running_loop().time() + 5
        while not reply.get('closed'):
            if asyncio.get_running_loop().time() >= deadline:
                raise TimeoutError('SIP shutdown is still pending')
            await asyncio.sleep(0.1)
            reply = await self._request('poll')
        self._retire_call()
        self._received_stop = True
        self._opened = False

    async def close_if_idle(self):
        async with self._lifecycle:
            if not self._opened:
                return True
            async with self._commands:
                if self._call_id:
                    return False
                reply = await self._request('close_idle')
                if reply.get('busy') is True:
                    return False
                self._running = False
                task, self._task = self._task, None
                if task:
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await task
                await self._finish_close(reply)
                return True

    async def close(self):
        async with self._lifecycle:
            if not self._opened:
                return
            self._running = False
            task, self._task = self._task, None
            if task:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            async with self._commands:
                reply = await self._request('close')
                await self._finish_close(reply)

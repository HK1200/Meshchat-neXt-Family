# SPDX-License-Identifier: 0BSD
"""A standard RNSh client without local subprocesses, PTYs or shell execution."""
import asyncio
import codecs
from collections import deque
import contextlib
import json
import math
import os
from pathlib import Path
import re
import shlex
import time
import uuid

from aiohttp import web
import RNS
from RNS.Utilities.rnsh import protocol
from meshchatnext.src.backend.path_utils import path_response_window, link_establishment_window

MAX_INPUT = 65536
MAX_OUTPUT = 250000
MAX_STATE = 4 * 1024 * 1024


def address(value):
    if not isinstance(value, str) or not re.fullmatch('[a-fA-F0-9]{32}', value):
        raise ValueError('Enter a 32-character RNSh destination')
    return value.lower()


def number(value, default, minimum, maximum):
    if value is None: return default
    if type(value) is not int or not minimum <= value <= maximum: raise ValueError('Invalid terminal size')
    return value


def configuration(data):
    if not isinstance(data, dict): raise ValueError('Invalid terminal settings')
    if data.get('mode', 'connect') != 'connect':
        raise ValueError('iOS can connect to remote RNSh hosts; local command listeners require a desktop')
    for field in ('config_path', 'identity_path', 'service', 'extra_args'):
        if data.get(field) not in (None, ''):
            raise ValueError('iOS uses this app’s identity and RNS interfaces; custom local paths and services are unavailable')
    destination = address(data.get('destination'))
    name = data.get('name') or 'Session ' + destination[:10]
    if not isinstance(name, str) or not name.strip() or len(name) > 120 or any(ord(c) < 32 for c in name):
        raise ValueError('Choose a session name up to 120 characters')
    command = data.get('remote_command') or ''
    if not isinstance(command, str) or len(command.encode()) > 4096 or '\x00' in command:
        raise ValueError('The remote command is too long')
    argv = shlex.split(command) if command else None
    if argv is not None and (len(argv) > 64 or any(len(part.encode()) > 1024 for part in argv)):
        raise ValueError('The remote command is too long')
    rows, cols = number(data.get('rows'), 40, 1, 1000), number(data.get('cols'), 120, 1, 1000)
    sample = protocol.ExecuteCommandMesssage(cmdline=argv, term='xterm-256color', rows=rows, cols=cols,
        pipe_stdin=False, pipe_stdout=False, pipe_stderr=False, hpix=0, vpix=0)
    if len(sample.pack()) > RNS.Link.MDU - 6:
        raise ValueError('That command is too long; connect first and type it in the terminal')
    timeout = data.get('timeout')
    if timeout not in (None, ''):
        if type(timeout) not in (int, float, str): raise ValueError('Invalid timeout')
        timeout = float(timeout)
        if not math.isfinite(timeout) or not 1 <= timeout <= 600: raise ValueError('Choose a timeout from 1 to 600 seconds')
    else: timeout = None
    flags = {}
    for field, default in (('mirror', False), ('no_id', False), ('autostart', True)):
        value = data.get(field, default)
        if type(value) is not bool: raise ValueError('Invalid ' + field)
        flags[field] = value
    return dict(mode='connect', destination=destination, name=name.strip(), remote_command=command,
                rows=rows, cols=cols, timeout=timeout, **flags)


class Session:
    def __init__(self, manager, identifier, config):
        self.manager, self.id, self.config = manager, identifier, config
        self.created_at = self.updated_at = time.time()
        self.status = 'stopped'
        self.last_error = ''
        self.last_exit_code = self.remote_exit_code = None
        self.output = deque()
        self.output_length = self.sequence = 0
        self.worker = self.link = self.channel = None
        self.inbox = asyncio.Queue(maxsize=128)
        self.input = bytearray()
        self.geometry = None
        self.stopping = False
        self.decoders = {key: codecs.getincrementaldecoder('utf-8')('replace') for key in (1, 2)}

    def record(self):
        return dict(id=self.id, name=self.config['name'], mode='connect', destination=self.config['destination'],
            config=dict(self.config), config_dir=None, listen_address=None, rows=self.config['rows'], cols=self.config['cols'],
            status=self.status, pid=None, last_exit_code=self.last_exit_code, remote_exit_code=self.remote_exit_code,
            last_error=self.last_error, last_command=None, created_at=self.created_at, updated_at=self.updated_at,
            output_seq=self.sequence, output_size=len(self.output), output_chunks=list(self.output)[-400:],
            output_text=''.join(row['text'] for row in self.output)[-50000:])

    def changed(self):
        self.updated_at = time.time(); self.manager.dirty = True
        self.manager.emit({'type': 'rnsh.session.change', 'session_id': self.id})

    def append(self, text):
        if not text: return
        self.sequence += 1
        row = dict(seq=self.sequence, text=text[-MAX_OUTPUT:], ts=time.time())
        self.output.append(row); self.output_length += len(row['text'])
        while self.output and (self.output_length > MAX_OUTPUT or len(self.output) > 4000):
            self.output_length -= len(self.output.popleft()['text'])
        self.updated_at = time.time(); self.manager.dirty = True
        self.manager.emit({'type': 'rnsh.output', 'session_id': self.id, 'chunk': row})

    def guard(self, *, check_link=True):
        if self.manager.closed or self.stopping: raise asyncio.CancelledError()
        if self.manager.blocked(self.config['destination']): raise PermissionError('This destination is blocked')
        if check_link and self.link is not None and self.link.status == RNS.Link.CLOSED: raise ConnectionError('The remote terminal connection closed')

    async def until(self, predicate, timeout):
        deadline = asyncio.get_running_loop().time() + timeout
        while not predicate():
            self.guard()
            if asyncio.get_running_loop().time() >= deadline: raise TimeoutError('The remote terminal did not respond')
            await asyncio.sleep(.02)
        self.guard()

    def incoming(self, message):
        def deliver():
            if self.stopping or self.manager.closed or self.worker is None or self.worker.done(): return
            try: self.inbox.put_nowait(message)
            except asyncio.QueueFull:
                self.last_error = 'Remote terminal output exceeded its receiving capacity'
                self.status = 'failed'; self.stopping = True
                if self.link is not None:
                    with contextlib.suppress(Exception): self.link.teardown()
                self.worker.cancel(); self.changed()
        if not self.manager.loop.is_closed():
            with contextlib.suppress(RuntimeError): self.manager.loop.call_soon_threadsafe(deliver)
        return True

    async def send(self, message):
        while not self.channel.is_ready_to_send():
            self.guard(); await asyncio.sleep(.02)
        self.guard()
        if len(message.pack()) > self.channel.mdu: raise ValueError('The terminal command is too long for this connection')
        self.channel.send(message)

    async def receive(self, timeout):
        deadline = self.manager.loop.time() + timeout
        while True:
            # A final output/exit message can already be verified and queued when
            # the peer closes. Drain it, while still checking cancellation/blocks.
            self.guard(check_link=self.inbox.empty())
            message = await asyncio.wait_for(self.inbox.get(), max(0, deadline - self.manager.loop.time()))
            self.guard(check_link=False)
            if isinstance(message, protocol.ErrorMessage):
                text = str(message.msg)[:240] or 'The remote host rejected the connection'
                if message.fatal: raise ConnectionError(text)
                self.append('\r\n' + text + '\r\n')
                continue
            return message

    async def run(self):
        try:
            self.guard()
            destination = bytes.fromhex(self.config['destination'])
            if not RNS.Transport.has_path(destination):
                self.append('Finding Reticulum path…\r\n')
                self.guard(); RNS.Transport.request_path(destination)
                wait = self.config['timeout'] or path_response_window(destination, self.manager.probe.reticulum)
                await self.until(lambda: RNS.Transport.has_path(destination), wait)
            self.guard()
            identity = RNS.Identity.recall(destination)
            if identity is None or RNS.Destination.hash_from_name_and_identity('rnsh', identity) != destination:
                raise ValueError('The destination is not a verified RNSh host')
            remote = RNS.Destination(identity, RNS.Destination.OUT, RNS.Destination.SINGLE, 'rnsh')
            self.guard(); self.link = RNS.Link(remote)
            self.append('Connecting…\r\n')
            await self.until(lambda: self.link.status == RNS.Link.ACTIVE,
                link_establishment_window(self.link, destination, self.manager.probe.reticulum))
            self.channel = self.link.get_channel()
            protocol.register_message_types(self.channel)
            self.channel.add_message_handler(self.incoming)
            if not self.config['no_id']:
                # Match the standard client's identity-state handoff before its version exchange.
                await asyncio.sleep(min(1, self.link.rtt * 1.1 + .05))
                self.guard(); self.link.identify(self.manager.probe.source.identity)
            await self.send(protocol.VersionInfoMessage())
            version = await self.receive(max(10, self.link.rtt * 20 + 1))
            if not isinstance(version, protocol.VersionInfoMessage) or version.protocol_version != protocol.PROTOCOL_VERSION:
                raise ValueError('The remote host uses an incompatible RNSh protocol')
            await self.send(protocol.ExecuteCommandMesssage(
                cmdline=shlex.split(self.config['remote_command']) if self.config['remote_command'] else None,
                pipe_stdin=False, pipe_stdout=False, pipe_stderr=False, term='xterm-256color',
                rows=self.config['rows'], cols=self.config['cols'], hpix=0, vpix=0))
            self.append('Connected.\r\n')
            while True:
                self.guard(check_link=self.inbox.empty())
                if self.geometry is not None and self.channel.is_ready_to_send():
                    rows, cols = self.geometry; self.geometry = None
                    await self.send(protocol.WindowSizeMessage(rows=rows, cols=cols, hpix=0, vpix=0))
                if self.input and self.channel.is_ready_to_send():
                    width = self.channel.mdu - protocol.StreamDataMessage.HEADER_LEN
                    part = bytes(self.input[:width])
                    await self.send(protocol.StreamDataMessage(protocol.StreamDataMessage.STREAM_ID_STDIN, part))
                    del self.input[:len(part)]
                try: message = await self.receive(.1)
                except TimeoutError: continue
                if isinstance(message, protocol.StreamDataMessage):
                    if message.stream_id in self.decoders:
                        self.append(self.decoders[message.stream_id].decode(message.data, final=message.eof))
                        if message.eof: self.decoders[message.stream_id].reset()
                elif isinstance(message, protocol.CommandExitedMessage):
                    self.command_exited(message.return_code)
                    return
        except asyncio.CancelledError:
            if self.status != 'failed': self.status = 'stopped'
        except Exception as error:
            self.status = 'failed'; self.last_error = str(error)[:240]
            self.append('\r\n' + self.last_error + '\r\n')
        finally:
            if self.channel is not None:
                with contextlib.suppress(Exception): self.channel.remove_message_handler(self.incoming)
            if self.link is not None:
                with contextlib.suppress(Exception): self.link.teardown()
            self.link = self.channel = None; self.input.clear(); self.changed()

    def command_exited(self, code):
        if type(code) is not int or not -(2**31) <= code <= 2**32 - 1:
            raise ValueError('Invalid remote command status')
        self.remote_exit_code = code
        self.last_exit_code = code if self.config['mirror'] else 0
        self.status = 'failed' if self.last_exit_code else 'stopped'
        if self.last_exit_code: self.last_error = 'Remote command exited with status ' + str(self.last_exit_code)

    def start(self):
        if self.worker is not None and not self.worker.done(): return
        self.stopping = False
        self.guard()
        self.last_error = ''; self.last_exit_code = self.remote_exit_code = None
        self.inbox = asyncio.Queue(maxsize=128); self.input.clear(); self.geometry = None
        for decoder in self.decoders.values(): decoder.reset()
        self.status = 'running'
        self.worker = self.manager.loop.create_task(self.run()); self.changed()

    async def stop(self):
        self.stopping = True
        if self.worker is None or self.worker.done():
            self.input.clear()
            return
        if self.worker is not None and not self.worker.done():
            self.worker.cancel(); await asyncio.gather(self.worker, return_exceptions=True)
        if self.status != 'failed': self.status = 'stopped'
        self.input.clear()
        self.changed()


class TerminalRuntime:
    def __init__(self, probe, folder, blocked, publish):
        self.probe, self.blocked, self.publish = probe, blocked, publish
        self.folder = Path(folder); self.folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.state = self.folder / 'sessions.json'
        self.sessions = {}; self.error = ''; self.dirty = False; self.closed = False
        self.loop = asyncio.get_running_loop(); self.events = set()
        try:
            if self.state.exists():
                if self.state.stat().st_size > MAX_STATE: raise ValueError()
                rows = json.loads(self.state.read_text())
                if not isinstance(rows, list) or len(rows) > 16: raise ValueError()
                for row in rows:
                    identifier = row['id']
                    if not isinstance(identifier, str) or not re.fullmatch('[a-f0-9]{32}', identifier) or identifier in self.sessions: raise ValueError()
                    session = Session(self, identifier, configuration(row['config']))
                    session.created_at = float(row['created_at'])
                    session.updated_at = float(row['updated_at'])
                    if not math.isfinite(session.created_at) or not math.isfinite(session.updated_at): raise ValueError()
                    text = row.get('output_text', '')
                    if not isinstance(text, str) or len(text) > 50000: raise ValueError()
                    if text: session.output.append(dict(seq=1, text=text, ts=session.updated_at)); session.sequence=1; session.output_length=len(text)
                    self.sessions[identifier] = session
        except (OSError, ValueError, TypeError, KeyError, RecursionError):
            self.sessions = {}; self.error = 'Saved terminal sessions could not be opened; restore the session file from your backup'

    def emit(self, value):
        if self.closed: return
        task = self.loop.create_task(self.publish(value)); self.events.add(task)
        task.add_done_callback(self.events.discard)
        task.add_done_callback(lambda done: done.exception() if not done.cancelled() else None)

    def register(self, router):
        router.add_get('/api/v1/rnsh/sessions', self.api)
        router.add_post('/api/v1/rnsh/sessions', self.api)
        router.add_delete('/api/v1/rnsh/sessions/{session_id}', self.api)
        router.add_get('/api/v1/rnsh/sessions/{session_id}/output', self.api)
        for action in ('start', 'stop', 'input', 'resize', 'clear'):
            router.add_post('/api/v1/rnsh/sessions/{session_id}/' + action, self.api)

    async def body(self, request):
        data = bytearray()
        async with asyncio.timeout(5):
            while len(data) <= 131072:
                part = await request.content.read(131073 - len(data))
                if not part: break
                data.extend(part)
        if len(data) > 131072: raise ValueError('Request is too large')
        value = json.loads(data or b'{}')
        if not isinstance(value, dict): raise ValueError('Invalid terminal request')
        return value

    def save(self):
        if not self.dirty or self.error: return
        rows = []
        for session in self.sessions.values():
            value = session.record()
            rows.append({key: value[key] for key in ('id', 'config', 'created_at', 'updated_at', 'output_text')})
        data = json.dumps(rows, ensure_ascii=False).encode()
        if len(data) > MAX_STATE: raise ValueError('Saved terminal history is too large')
        temporary = self.folder / (uuid.uuid4().hex + '.tmp')
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, 'wb') as stream: stream.write(data); stream.flush(); os.fsync(stream.fileno())
            temporary.replace(self.state); self.dirty = False
        finally: temporary.unlink(missing_ok=True)

    async def api(self, request):
        try:
            if self.error: return web.json_response({'message': self.error}, status=503)
            if self.closed: return web.json_response({'message': 'Terminal sessions are stopped'}, status=503)
            identifier = request.match_info.get('session_id')
            session = self.sessions.get(identifier) if identifier else None
            if identifier and session is None: raise web.HTTPNotFound()
            if request.method == 'GET':
                if session is None: return web.json_response({'sessions': [s.record() for s in self.sessions.values()]}, headers={'Cache-Control': 'no-store'})
                cursor = request.query.get('cursor', '0')
                if not re.fullmatch('[0-9]{1,20}', cursor): raise ValueError('Invalid output cursor')
                return web.json_response({'chunks': [row for row in session.output if row['seq'] > int(cursor)], 'next_cursor': session.sequence}, headers={'Cache-Control': 'no-store'})
            if request.method == 'DELETE':
                await session.stop(); del self.sessions[identifier]; self.dirty=True; self.save()
                return web.json_response({'message': 'Session removed'})
            data = await self.body(request)
            if session is None:
                if len(self.sessions) >= 16: raise ValueError('Remove an old session before adding another')
                config = configuration(data)
                if self.blocked(config['destination']): raise ValueError('This destination is blocked')
                session = Session(self, uuid.uuid4().hex, config)
                self.sessions[session.id] = session; self.dirty=True
                try: self.save()
                except (OSError, ValueError):
                    del self.sessions[session.id]
                    raise
                # A failed persistence operation must never execute a command
                # after the UI has already reported that creation failed.
                if config['autostart']: session.start()
            else:
                action = request.path.rsplit('/', 1)[-1]
                if action == 'start': session.start()
                elif action == 'stop': await session.stop()
                elif action == 'input':
                    session.guard()
                    text = data.get('text'); newline = data.get('newline', False)
                    if not isinstance(text, str) or type(newline) is not bool: raise ValueError('Enter terminal input')
                    if newline and not text.endswith('\n'): text += '\n'
                    raw = text.encode()
                    if len(raw) + len(session.input) > MAX_INPUT: raise ValueError('Wait for the terminal to catch up before sending more input')
                    if session.worker is None or session.worker.done(): raise ValueError('Start the terminal session first')
                    session.input.extend(raw)
                elif action == 'resize':
                    rows = number(data.get('rows'), session.config['rows'], 1, 1000)
                    cols = number(data.get('cols'), session.config['cols'], 1, 1000)
                    session.config.update(rows=rows, cols=cols); session.geometry=(rows, cols); self.dirty=True
                elif action == 'clear':
                    session.output.clear(); session.output_length=session.sequence=0; session.changed()
                self.save()
            return web.json_response({'session': session.record()})
        except (ValueError, PermissionError) as error:
            return web.json_response({'message': str(error)}, status=400)
        except OSError:
            return web.json_response({'message': 'Terminal settings could not be saved'}, status=507)

    async def tick(self):
        if self.closed or self.error: return
        try: self.save()
        except (OSError, ValueError):
            for session in tuple(self.sessions.values()): await session.stop()
            self.error = 'Terminal sessions could not be saved; restore available storage before reconnecting'

    async def close(self):
        self.closed = True
        for session in tuple(self.sessions.values()): await session.stop()
        try: self.save()
        except (OSError, ValueError):
            self.error = 'Terminal history could not be saved; restore available storage before reconnecting'
        if self.events: await asyncio.gather(*tuple(self.events), return_exceptions=True)

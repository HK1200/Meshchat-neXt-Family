"""Reticulum TCP client that recovers from write failures as well as read failures."""

import socket
import threading

import RNS
from RNS.Interfaces.TCPInterface import HDLC, TCPClientInterface


class FamilyTCPInterface(TCPClientInterface):
    def __init__(self, owner, configuration):
        self._socket_lock = threading.Lock()
        self._send_lock = threading.Lock()
        super().__init__(owner, configuration)

    def connect(self, initial=False):
        # Busy public peers can exceed the upstream 3-announces-per-second startup limit.
        self.ic_burst_freq_new = max(self.ic_burst_freq_new, 20)
        self.ic_burst_freq = max(self.ic_burst_freq, 20)
        if self.detached:
            return False

        connection = None
        try:
            connection = socket.create_connection((self.target_ip, self.target_port), self.connect_timeout)
            connection.settimeout(None)
            self._configure_socket(connection)
        except OSError as error:
            if connection is not None:
                connection.close()
            if initial:
                RNS.log(f"Initial connection to {self} failed: {error}. Reticulum will retry.", RNS.LOG_WARNING)
                return False
            raise

        with self._socket_lock:
            if self.detached:
                connection.close()
                return False
            if self.socket is not None:
                self._close_socket(self.socket)
            self.socket = connection
            self.family_connection_epoch = getattr(self, "family_connection_epoch", 0) + 1
            self.never_connected = False
            self.online = True
        return True

    def _configure_socket(self, connection):
        connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        connection.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        for name, value in (
            ("TCP_USER_TIMEOUT", self.TCP_USER_TIMEOUT * 1000),
            ("TCP_KEEPIDLE", self.TCP_PROBE_AFTER),
            ("TCP_KEEPALIVE", self.TCP_PROBE_AFTER),
            ("TCP_KEEPINTVL", self.TCP_PROBE_INTERVAL),
            ("TCP_KEEPCNT", self.TCP_PROBES),
        ):
            option = getattr(socket, name, None)
            if option is not None:
                try:
                    connection.setsockopt(socket.IPPROTO_TCP, option, value)
                except OSError:
                    # Android and desktop kernels expose different optional TCP settings.
                    pass

    def process_outgoing(self, data):
        with self._send_lock:
            connection = self.socket
            if not self.online or self.detached or connection is None:
                return
            framed = bytes([HDLC.FLAG]) + HDLC.escape(data) + bytes([HDLC.FLAG])
            try:
                connection.sendall(framed)
            except OSError as error:
                with self._socket_lock:
                    if self.socket is connection and not self.detached:
                        self.online = False
                        RNS.log(f"Write to {self} failed: {error}. Reconnecting.", RNS.LOG_WARNING)
                        # Wake the reader, which owns the normal Reticulum reconnect loop.
                        self._close_socket(connection)
                return
            self.txb += len(framed)

    @staticmethod
    def _close_socket(connection):
        try:
            connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        connection.close()

    def detach(self):
        with self._socket_lock:
            super().detach()

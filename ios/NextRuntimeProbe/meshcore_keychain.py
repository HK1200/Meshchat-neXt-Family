"""Secure credentials provider for neXt's unchanged MeshCore node controller."""
import json
import re


class IOSNodePasswords:
    @staticmethod
    def _slot(owner, peer, role):
        if (not isinstance(owner, str) or not re.fullmatch('[a-f0-9]{64}', owner)
                or not isinstance(peer, str) or not re.fullmatch('[a-f0-9]{64}', peer)
                or role not in ('member', 'admin')):
            raise ValueError('Invalid MeshCore node credential slot')
        return dict(owner=owner, peer=peer, role=role)

    def _call(self, operation, owner, peer, role, **values):
        from _next_credentials import request
        payload = dict(self._slot(owner, peer, role), operation=operation, **values)
        response = json.loads(request(json.dumps(payload)))
        if not isinstance(response, dict) or response.get('error') or 'value' not in response:
            raise ValueError('Secure node password storage is unavailable')
        return response['value']

    def has(self, owner, peer, role):
        value = self._call('has', owner, peer, role)
        if type(value) is not bool:
            raise ValueError('Invalid secure-storage response')
        return value

    def load(self, owner, peer, role):
        value = self._call('load', owner, peer, role)
        if not isinstance(value, str):
            raise ValueError('Invalid secure-storage response')
        return value

    def save(self, owner, peer, role, password):
        if not isinstance(password, str) or '\0' in password or len(password.encode('utf-8')) > 64:
            raise ValueError('Use a password of at most 64 UTF-8 bytes without NUL')
        if self._call('save', owner, peer, role, password=password) is not True:
            raise ValueError('Secure node password could not be saved')

    def forget(self, owner, peer, role):
        if self._call('forget', owner, peer, role) is not True:
            raise ValueError('Secure node password could not be removed')

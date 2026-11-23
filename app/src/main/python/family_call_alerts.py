# SPDX-License-Identifier: 0BSD
"""Guardian-selected recipient call routes. No provider is chosen automatically."""
import copy
import time
from family_call_hints import PendingHint, parse_route, post
from family_call_wake import destination_hash, hex_value, voice_hash


def bound_contact(state, contact_id):
    if type(contact_id) is not int:
        raise ValueError("Choose an individually approved voice contact")
    matches = [c for c in state.get("contacts", []) if c.get("id") == contact_id]
    if len(matches) != 1:
        raise ValueError("This contact approval has changed")
    contact = matches[0]
    addresses = contact.get("addresses", {})
    address, voice = addresses.get("lxmf", "").lower(), addresses.get("lxst", "").lower()
    key = contact.get("identityPublicKey", "").lower()
    if not hex_value(address, 16) or not hex_value(voice, 16) or not hex_value(key, 64):
        raise ValueError("Receive a verified contact code or signed message and save its voice address first")
    raw = bytes.fromhex(key)
    if destination_hash("lxmf.delivery", raw) != address or voice_hash(raw) != voice:
        raise ValueError("The saved messaging and voice addresses do not match this contact's identity")
    return dict(contactId=contact_id, recipient=address, voice=voice, publicKey=key)


def route_for(state, contact_id):
    try:
        binding = bound_contact(state, contact_id)
        records = state.get("callAlertRoutes", {})
        record = records.get(str(contact_id)) if type(records) is dict else None
        if type(record) is not dict or record.get("binding") != binding:
            return None
        route = parse_route(binding["recipient"], record.get("route"))
        if route and route.public_key == binding["publicKey"]:
            return route
    except (ValueError, TypeError, AttributeError):
        pass
    return None


def set_route(state, contact_id, entry):
    binding = bound_contact(state, contact_id)
    previous = state.get("callAlertRoutes", {})
    if type(previous) is not dict:
        raise ValueError("Stored call-alert routes need review")
    records = copy.deepcopy(previous)
    if entry is None:
        records.pop(str(contact_id), None)
    else:
        if type(entry) is not dict or set(entry) != {"provider", "audience"}:
            raise ValueError("Enter only the HTTPS provider and audience supplied by this contact")
        proposed = {**entry, "public_key": binding["publicKey"]}
        route = parse_route(binding["recipient"], proposed)
        if route is None:
            raise ValueError("Use an HTTPS provider without a path or login, and a valid audience")
        records[str(contact_id)] = dict(binding=binding, route=dict(provider=route.provider,
            audience=route.audience, public_key=route.public_key))
    if len(records) > 100:
        raise ValueError("At most 100 approved call routes are supported")
    state["callAlertRoutes"] = records
    return route_for(state, contact_id)


def reconcile_routes(state):
    records = state.get("callAlertRoutes", {})
    if type(records) is not dict:
        return
    state["callAlertRoutes"] = {key: value for key, value in records.items()
        if type(key) is str and key.isdecimal() and route_for(state, int(key)) is not None}


class FamilyCallHints:
    def __init__(self, identity, state, lock, *, sender=post, wall_clock=time.time):
        self.identity, self.state, self.lock, self.sender = identity, state, lock, sender
        self.wall_clock = wall_clock

    def start(self, contact_id, call_id, voice):
        with self.lock:
            route = route_for(self.state, contact_id)
            if not self.state.get("voiceEnabled") or not route or route.voice != voice:
                return None
            binding = bound_contact(self.state, contact_id)
        def permitted():
            with self.lock:
                try:
                    return bool(self.state.get("voiceEnabled") and
                        bound_contact(self.state, contact_id) == binding and
                        route_for(self.state, contact_id) == route)
                except (ValueError, TypeError, AttributeError):
                    return False
        handle = PendingHint(self.identity, route, call_id, permitted, sender=self.sender, wall_clock=self.wall_clock)
        return handle if handle.start() else None

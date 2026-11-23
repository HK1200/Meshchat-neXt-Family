"""Native-only enrollment metadata: saved contacts plus bound verified keys.

No enrollment secret or Apple device token enters this module or its database.
"""

import hashlib
import json
import re
import RNS


def _contacts(history, remembered=None):
    contacts = []
    for contact in history.contacts().values():
        address = contact.get("lxmf_address")
        if not isinstance(address, str) or not re.fullmatch(r"[a-f0-9]{32}", address):
            continue
        key = None
        recalled = RNS.Identity.recall(bytes.fromhex(address))
        for identity in (recalled, (remembered or {}).get(address)):
            if identity is None:
                continue
            try:
                bound = RNS.Destination.hash_from_name_and_identity(
                    "lxmf.delivery", identity
                )
                public = identity.get_public_key()
                if (
                    bound.hex() == address
                    and isinstance(public, bytes)
                    and len(public) == 64
                ):
                    key = public.hex()
                    break
            except (AttributeError, TypeError, ValueError):
                pass
        contacts.append(
            {
                "name": contact["name"],
                "addresses": {"lxmf": address},
                "identityPublicKey": key,
            }
        )
    return contacts


def snapshot(history, source, mailbox):
    return {
        "address": source.hash.hex(),
        "mailbox": {"address": mailbox.snapshot()["address"]},
        "contacts": _contacts(history),
    }


def call_snapshot(history, source, voice, *, public_keys=None, block_snapshot=()):
    """Public enrollment metadata only, with the actual incoming-call policy.

    The private Reticulum key stays in its own runtime/container. Neither an
    unsigned name nor a recalled key under a different address grants access.
    Turning calling off, DND, removal or a ban strips provider eligibility.
    """
    if public_keys is None:
        public_keys = []
    if (type(public_keys) is not list or len(public_keys) > 256 or
            any(type(key) is not str or re.fullmatch(r"[a-f0-9]{128}", key) is None for key in public_keys) or
            len(set(public_keys)) != len(public_keys)):
        raise ValueError("Select at most 256 distinct public contact keys")
    remembered = {}
    for key in public_keys:
        peer = RNS.Identity(create_keys=False)
        peer.load_public_key(bytes.fromhex(key))
        address = RNS.Destination.hash_from_name_and_identity("lxmf.delivery", peer).hex()
        remembered[address] = peer
    identity = source.identity
    public = identity.get_public_key()
    if (not isinstance(public, bytes) or len(public) != 64 or
            RNS.Destination.hash_from_name_and_identity("lxmf.delivery", identity) != source.hash):
        raise ValueError("The local call identity does not match the messaging address")
    enabled = bool(voice is not None and voice.available and not voice.closed and
                   voice.config.telephone_enabled.get() is True and
                   voice.call_policy.get("do_not_disturb_enabled") is False)
    saved = [{"name": row["name"], "addresses": row["addresses"]} for row in _contacts(history)]
    saved.sort(key=lambda row: row["addresses"]["lxmf"])
    # This digest intentionally excludes the volatile recall cache and media
    # readiness/profile. A cold start or codec change cannot revoke consent.
    policy = dict(voice.call_policy) if voice is not None else {}
    policy["blocked_callers"] = sorted(voice.blocked_callers) if voice is not None and hasattr(voice, "blocked_callers") else []
    policy["blocked_destinations"] = sorted({row["destination_hash"] for row in block_snapshot})
    policy["contacts"] = sorted(row["addresses"]["lxmf"] for row in saved)
    policy["owner"] = public.hex()
    policy["enabled"] = enabled
    digest = hashlib.sha256(json.dumps(policy, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    contacts = []
    if enabled:
        for row in _contacts(history, remembered):
            key = row["identityPublicKey"]
            if key is None:
                continue
            peer = RNS.Identity(create_keys=False)
            peer.load_public_key(bytes.fromhex(key))
            if not voice.caller_allowed(peer.hash):
                continue
            contacts.append({**row, "addresses": {**row["addresses"], "voice":
                RNS.Destination.hash_from_name_and_identity("lxst.telephony", peer).hex()}})
    return {
        "address": source.hash.hex(),
        "voiceAddress": RNS.Destination.hash_from_name_and_identity("lxst.telephony", identity).hex(),
        "identityPublicKey": public.hex(),
        "enabled": enabled,
        "contacts": contacts,
        "savedContacts": saved,
        "policyDigest": digest,
    }

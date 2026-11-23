"""Native-only enrollment metadata: saved contacts plus bound verified keys.

No enrollment secret or Apple device token enters this module or its database.
"""

import re
import RNS


def _contacts(history):
    contacts = []
    for contact in history.contacts().values():
        address = contact.get("lxmf_address")
        if not isinstance(address, str) or not re.fullmatch(r"[a-f0-9]{32}", address):
            continue
        key = None
        identity = RNS.Identity.recall(bytes.fromhex(address))
        if identity is not None:
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


def call_snapshot(history, source, voice):
    """Public enrollment metadata only, with the actual incoming-call policy.

    The private Reticulum key stays in its own runtime/container. Neither an
    unsigned name nor a recalled key under a different address grants access.
    Turning calling off, DND, removal or a ban strips provider eligibility.
    """
    identity = source.identity
    public = identity.get_public_key()
    if (not isinstance(public, bytes) or len(public) != 64 or
            RNS.Destination.hash_from_name_and_identity("lxmf.delivery", identity) != source.hash):
        raise ValueError("The local call identity does not match the messaging address")
    enabled = bool(voice is not None and voice.available and not voice.closed and
                   voice.config.telephone_enabled.get() is True and
                   voice.call_policy.get("do_not_disturb_enabled") is False)
    contacts = []
    if enabled:
        for row in _contacts(history):
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
    }

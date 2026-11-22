"""Native-only enrollment metadata: saved contacts plus bound verified keys.

No enrollment secret or Apple device token enters this module or its database.
"""

import re
import RNS


def snapshot(history, source, mailbox):
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
    return {
        "address": source.hash.hex(),
        "mailbox": {"address": mailbox.snapshot()["address"]},
        "contacts": contacts,
    }

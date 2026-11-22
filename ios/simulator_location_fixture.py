"""Validate only signed, synthetic locations for a loopback simulator fixture."""
import time


def valid_synthetic_location(message, *, now=None):
    import LXMF
    from family_location import valid_fix
    from meshchatnext.src.backend.telemetry_utils import Telemeter

    if not message.signature_validated or message.content_as_string() != '':
        return False
    if not isinstance(message.fields, dict) or set(message.fields) != {LXMF.FIELD_TELEMETRY}:
        return False
    packed = message.fields[LXMF.FIELD_TELEMETRY]
    if not isinstance(packed, bytes) or not 0 < len(packed) <= 65536:
        return False
    try:
        now = time.time() if now is None else now
        telemetry = Telemeter.from_packed(packed)
        fix = valid_fix(telemetry['location'], now)
        return (abs(fix['latitude'] - 48.75) <= .002
                and abs(fix['longitude'] + 122.48) <= .002
                and now - 120 <= fix['last_update'] <= now + 30)
    except (ValueError, KeyError, TypeError, OverflowError):
        return False

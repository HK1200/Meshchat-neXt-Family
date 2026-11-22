"""Bounded LXMF files/photos using neXt's existing browser field format."""
import base64
import binascii

import LXMF
import voice_notes

# Match neXt's 10 MB direct-delivery default, leaving room for LXMF metadata.
MAX_BYTES = 9_950_000
MAX_ITEMS = 32


def filename(value):
    value = value if isinstance(value, str) else ""
    value = value.replace("\\", "/").rsplit("/", 1)[-1]
    value = "".join(c for c in value if c.isprintable() and c not in "\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069")
    return value.strip(". ")[:120] or "attachment"


def image_type(data):
    if data.startswith(b"\x89PNG\r\n\x1a\n"): return "png"
    if data.startswith(b"\xff\xd8\xff"): return "jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")): return "gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP": return "webp"
    if data.startswith(b"BM"): return "bmp"
    if data[4:8] == b"ftyp" and data[8:12] in (b"avif", b"avis"): return "avif"
    return None


def _decode(value):
    if not isinstance(value, str) or len(value) > ((MAX_BYTES + 2) // 3) * 4:
        raise ValueError("Attachment exceeds the 10 MB direct-message budget")
    try:
        return base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("Invalid attachment data") from None


def outgoing(fields, content=""):
    if not isinstance(fields, dict) or set(fields) - {"image", "file_attachments", "audio"}:
        raise ValueError("Only file, photo and voice attachment fields are supported here")
    result, total, count = {}, len(content.encode("utf-8")), 0
    if "image" in fields:
        image = fields["image"]
        if not isinstance(image, dict): raise ValueError("Invalid photo attachment")
        data = _decode(image.get("image_bytes"))
        detected = image_type(data)
        if not detected: raise ValueError("Unsupported photo format; use PNG, JPEG, GIF, WebP, BMP or AVIF")
        result[LXMF.FIELD_IMAGE] = ["jpg" if detected == "jpeg" else detected, data]
        total += len(data); count += 1
    if "audio" in fields:
        audio = fields["audio"]
        if not isinstance(audio, dict): raise ValueError("Invalid voice attachment")
        mode, data = voice_notes.encode(audio.get("audio_mode"), _decode(audio.get("audio_bytes")))
        result[LXMF.FIELD_AUDIO] = [mode, data]
        total += len(data); count += 1
    if "file_attachments" in fields:
        files = fields["file_attachments"]
        if not isinstance(files, list) or not 1 <= len(files) <= MAX_ITEMS:
            raise ValueError("Choose between 1 and 32 attachments")
        result[LXMF.FIELD_FILE_ATTACHMENTS] = []
        for item in files:
            if not isinstance(item, dict): raise ValueError("Invalid file attachment")
            data = _decode(item.get("file_bytes"))
            total += len(data); count += 1
            if total > MAX_BYTES: raise ValueError("Attachments exceed the 10 MB direct-message budget")
            result[LXMF.FIELD_FILE_ATTACHMENTS].append([filename(item.get("file_name")), data])
    if total > MAX_BYTES or count > MAX_ITEMS:
        raise ValueError("Attachments exceed the direct-message budget (10 MB / 32 items)")
    return result


def incoming(fields):
    """Keep valid bounded data; malformed peer fields must not discard text."""
    if not isinstance(fields, dict): return {}
    result, total = {}, 0
    image = fields.get(LXMF.FIELD_IMAGE)
    if isinstance(image, (list, tuple)) and len(image) == 2 and isinstance(image[1], bytes):
        data = image[1]; detected = image_type(data)
        if detected and len(data) <= MAX_BYTES:
            total = len(data)
            result["image"] = dict(image_type="jpg" if detected == "jpeg" else detected,
                                   image_size=len(data), image_bytes=base64.b64encode(data).decode("ascii"))
    audio = fields.get(LXMF.FIELD_AUDIO)
    if isinstance(audio, (list, tuple)) and len(audio) == 2 and voice_notes.valid(audio[0], audio[1]):
        mode, data = audio
        if total + len(data) <= MAX_BYTES:
            total += len(data)
            result["audio"] = dict(audio_mode=mode, audio_size=len(data), audio_bytes=base64.b64encode(data).decode("ascii"))
    files = fields.get(LXMF.FIELD_FILE_ATTACHMENTS)
    if isinstance(files, (list, tuple)):
        items = []
        for item in files[:MAX_ITEMS - len(result)]:
            if not isinstance(item, (list, tuple)) or len(item) != 2 or not isinstance(item[1], bytes): continue
            name, data = item
            if total + len(data) > MAX_BYTES: continue
            total += len(data)
            items.append(dict(file_name=filename(name), file_size=len(data), file_bytes=base64.b64encode(data).decode("ascii")))
        if items: result["file_attachments"] = items
    return result


def slim(row):
    """Conversation pages/events carry metadata, never many MB of inline blobs."""
    fields = dict(row.get("fields") or {})
    if "image" in fields: fields["image"] = dict(fields["image"], image_bytes=None)
    if "audio" in fields: fields["audio"] = dict(fields["audio"], audio_bytes=None)
    if "file_attachments" in fields:
        fields["file_attachments"] = [dict(item, file_bytes=None) for item in fields["file_attachments"]]
    result = {key: value for key, value in row.items() if key != "_telemetry_data"}
    if "fields" in row:
        result["fields"] = fields
    return result

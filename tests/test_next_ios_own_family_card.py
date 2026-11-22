"""The neXt own-card endpoint stays private and imports into Family offline."""

from contextlib import ExitStack
from pathlib import Path
import json
from urllib.error import HTTPError
from urllib.parse import urljoin
from urllib.request import urlopen

import pytest
from test_next_ios_tcp_integration import api, backend, run_server, start, wait


def test_private_own_card_uses_saved_name_and_public_identity_only(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "app/src/main/python"))
    from family_cards import parse

    app = tmp_path / "app"
    app.mkdir()
    ready = app / "backend.url"
    settings = app / "peers.json"
    settings.write_text(
        json.dumps(
            {"peers": [{"id": "off", "host": "127.0.0.1", "port": 9, "enabled": False}]}
        )
    )
    with ExitStack() as stack:
        start(stack, run_server, app, ready, settings)
        wait(ready.is_file)
        base = backend(ready)
        config = api(base, "config")[1]["config"]
        text = api(base, "preview/contact-card")[1]["contact_card"]
        card = parse(text)
        assert card["name"] == config["display_name"]
        assert card["addresses"] == {"lxmf": config["lxmf_address_hash"]}
        assert len(card["identityPublicKey"]) == 128
        assert set(json.loads(text)) == {
            "format",
            "version",
            "name",
            "addresses",
            "identityPublicKey",
        }
        with pytest.raises(HTTPError) as denied:
            urlopen(urljoin(base, "/api/v1/preview/contact-card"), timeout=5)
        assert denied.value.code == 403
        assert (app / "reticulum/identity").read_bytes().hex() not in text

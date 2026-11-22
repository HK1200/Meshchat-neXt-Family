"""Only saved contacts with a cryptographically bound identity may enroll."""

from pathlib import Path
from types import SimpleNamespace
import sys
import RNS

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ios/NextRuntimeProbe"))
from push_receiving import snapshot


def test_enrollment_state_rejects_a_key_recalled_under_the_wrong_destination(
    monkeypatch,
):
    identity = RNS.Identity()
    valid = RNS.Destination.hash_from_name_and_identity("lxmf.delivery", identity).hex()
    wrong = "cd" * 16
    monkeypatch.setattr(RNS.Identity, "recall", lambda address: identity)
    history = SimpleNamespace(
        contacts=lambda: {
            valid: {"lxmf_address": valid, "name": "Verified"},
            wrong: {"lxmf_address": wrong, "name": "Unverified"},
        }
    )
    result = snapshot(
        history,
        SimpleNamespace(hash=b"o" * 16),
        SimpleNamespace(snapshot=lambda: {"address": "ab" * 16}),
    )
    assert result["address"] == b"o".hex() * 16 and result["mailbox"] == {
        "address": "ab" * 16
    }
    valid_row, wrong_row = result["contacts"]
    assert valid_row["identityPublicKey"] == identity.get_public_key().hex()
    assert wrong_row["identityPublicKey"] is None
    assert set(result) == {"address", "mailbox", "contacts"}
    assert all(
        set(row) == {"name", "addresses", "identityPublicKey"}
        for row in result["contacts"]
    )


def test_unknown_keys_and_non_lxmf_contacts_cannot_be_added_to_push_approvals(
    monkeypatch,
):
    monkeypatch.setattr(RNS.Identity, "recall", lambda address: None)
    history = SimpleNamespace(
        contacts=lambda: {
            1: {"lxmf_address": "aa" * 16, "name": "Pending announce"},
            2: {"name": "SIP only"},
            3: {"lxmf_address": "bad", "name": "Malformed"},
        }
    )
    result = snapshot(
        history,
        SimpleNamespace(hash=b"o" * 16),
        SimpleNamespace(snapshot=lambda: {"address": ""}),
    )
    assert result["contacts"] == [
        {
            "name": "Pending announce",
            "addresses": {"lxmf": "aa" * 16},
            "identityPublicKey": None,
        }
    ]
    assert result["mailbox"]["address"] == ""


def test_actual_enrollment_metadata_requires_the_private_session_and_excludes_secrets(
    tmp_path,
):
    import json
    from contextlib import ExitStack
    from urllib.error import HTTPError
    from urllib.parse import urlsplit
    from urllib.request import urlopen

    import pytest
    from test_next_ios_tcp_integration import api, backend, run_server, start, wait

    settings = tmp_path / "settings.json"
    settings.write_text(
        json.dumps(
            {"peers": [{"id": "off", "host": "127.0.0.1", "port": 9, "enabled": False}]}
        )
    )
    ready = tmp_path / "backend.url"
    with ExitStack() as stack:
        start(stack, run_server, tmp_path, ready, settings)
        wait(ready.exists)
        base = backend(ready)
        endpoint = (
            "http://" + urlsplit(base).netloc + "/api/v1/preview/push-enrollment-state"
        )
        with pytest.raises(HTTPError) as denied:
            urlopen(endpoint, timeout=5)
        assert denied.value.code == 403
        status, result = api(base, "preview/push-enrollment-state")
        assert status == 200 and len(result["address"]) == 32
        assert result["contacts"] == [] and result["mailbox"] == {"address": ""}
        token = api(base, "auth/csrf")[1]["csrf_token"]
        assert (
            api(
                base,
                "telephone/contacts",
                body={"name": "Private saved name", "lxmf_address": "cd" * 16},
                token=token,
            )[0]
            == 200
        )
        result = api(base, "preview/push-enrollment-state")[1]
        assert result["contacts"] == [
            {
                "name": "Private saved name",
                "addresses": {"lxmf": "cd" * 16},
                "identityPublicKey": None,
            }
        ]
        assert set(result) == {"address", "mailbox", "contacts"}

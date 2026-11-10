import importlib.util
from pathlib import Path

import pytest


source = Path(__file__).resolve().parents[1] / "app/src/main/python/family_cards.py"
spec = importlib.util.spec_from_file_location("family_contact_cards", source)
cards = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cards)


def test_meshcore_mobile_contact_qr_reads_name_and_normalizes_key():
    key = "AB" * 32
    qr = f"meshcore://contact/add?name=Example+Contact&public_key={key}&type=1"

    assert cards.parse(qr) == {
        "name": "Example Contact",
        "addresses": {"meshcore": key.lower()},
    }


@pytest.mark.parametrize("contact_type", ["2", "3", "4"])
def test_meshcore_contact_qr_excludes_non_companion_nodes(contact_type):
    qr = f"meshcore://contact/add?public_key={'ab' * 32}&type={contact_type}"

    with pytest.raises(ValueError, match="companion contact code"):
        cards.parse(qr)


@pytest.mark.parametrize("key", ["abc", ("ab" * 32) + "&public_key=" + ("cd" * 32)])
def test_meshcore_contact_qr_requires_one_full_key(key):
    with pytest.raises(ValueError, match="full MeshCore public key"):
        cards.parse(f"meshcore://contact/add?public_key={key}&type=1")

"""The pinned SIP sources survive transient transfers without trusting partial files."""
import hashlib
import http.client
import importlib.util
import io
from pathlib import Path
import urllib.error

import pytest

spec = importlib.util.spec_from_file_location("ios_build_sip", Path(__file__).parents[1] / "ios/build-sip.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
CONTENT = b"pinned source archive"
DIGEST = hashlib.sha256(CONTENT).hexdigest()


@pytest.mark.parametrize("error", [urllib.error.URLError("timeout"), TimeoutError(), ConnectionResetError(),
                                    http.client.IncompleteRead(b"partial"), urllib.error.HTTPError("https://example.invalid", 503, "unavailable", {}, None)])
def test_transient_transfer_retries_then_accepts_only_the_pinned_bytes(tmp_path, error):
    archive = tmp_path / "source.tar"
    requests, delays = [], []
    def opener(url, timeout):
        requests.append((url, timeout))
        if len(requests) == 1:
            raise error
        return io.BytesIO(CONTENT)
    module.ensure_source(archive, "https://example.invalid", DIGEST, opener=opener, pause=delays.append)
    assert archive.read_bytes() == CONTENT
    assert requests == [("https://example.invalid", 180)] * 2
    assert delays == [1]
    assert not archive.with_suffix(".part").exists()


def test_interrupted_body_is_discarded_before_retry(tmp_path):
    archive = tmp_path / "source.tar"
    class Broken(io.BytesIO):
        def read(self, size=-1):
            if self.tell():
                raise http.client.IncompleteRead(b"partial")
            return super().read(3)
    opened = [Broken(CONTENT), io.BytesIO(CONTENT)]
    module.ensure_source(archive, "https://example.invalid", DIGEST, opener=lambda *a, **kw: opened.pop(0), pause=lambda _: None)
    assert archive.read_bytes() == CONTENT
    assert not archive.with_suffix(".part").exists()


def test_three_failed_attempts_leave_no_partial_or_promoted_archive(tmp_path):
    archive = tmp_path / "source.tar"
    attempts, delays = [], []
    def opener(*args, **kwargs):
        attempts.append(True)
        raise TimeoutError("network timeout")
    with pytest.raises(TimeoutError):
        module.ensure_source(archive, "https://example.invalid", DIGEST, opener=opener, pause=delays.append)
    assert len(attempts) == 3
    assert delays == [1, 2]
    assert not archive.exists() and not archive.with_suffix(".part").exists()


def test_wrong_checksum_is_not_retried_or_promoted(tmp_path):
    archive = tmp_path / "source.tar"
    def no_pause(_):
        pytest.fail("Checksum mismatches must not be treated as transient")
    with pytest.raises(ValueError, match="checksum mismatch"):
        module.ensure_source(archive, "https://example.invalid", DIGEST, opener=lambda *a, **kw: io.BytesIO(b"wrong source"), pause=no_pause)
    assert not archive.exists() and not archive.with_suffix(".part").exists()


def test_non_transient_http_error_is_not_retried(tmp_path):
    error = urllib.error.HTTPError("https://example.invalid", 404, "missing", {}, None)
    def opener(*args, **kwargs):
        raise error
    with pytest.raises(urllib.error.HTTPError) as caught:
        module.ensure_source(tmp_path / "source.tar", "https://example.invalid", DIGEST, opener=opener, pause=lambda _: pytest.fail("404 retry"))
    assert caught.value is error


@pytest.mark.parametrize("content,valid", [(CONTENT, True), (b"modified cache", False)])
def test_existing_cache_is_verified_without_network_or_replacement(tmp_path, content, valid):
    archive = tmp_path / "source.tar"
    archive.write_bytes(content)
    def offline(*args, **kwargs):
        pytest.fail("Cached sources must be verified before using the network")
    if valid:
        module.ensure_source(archive, "https://example.invalid", DIGEST, opener=offline)
    else:
        with pytest.raises(ValueError, match="checksum mismatch"):
            module.ensure_source(archive, "https://example.invalid", DIGEST, opener=offline)
    assert archive.read_bytes() == content


def test_checksum_verification_supports_the_xcode_python39_fallback(tmp_path, monkeypatch):
    monkeypatch.delattr(module.hashlib, "file_digest", raising=False)
    archive = tmp_path / "source.tar"
    module.ensure_source(archive, "https://example.invalid", DIGEST, opener=lambda *a, **kw: io.BytesIO(CONTENT))
    assert archive.read_bytes() == CONTENT

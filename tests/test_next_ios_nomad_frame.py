"""The opaque renderer can load public code, never private app APIs."""
import ast
import inspect
from pathlib import Path
import sys
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'ios/NextRuntimeProbe'))
from nomad_frame import public_frame_resource, build_nomad_crash_tab_csp


@pytest.mark.parametrize('path', ['/nomad-crash-tab.html', '/assets/vendor-vue-hash.js',
    '/assets/nomad-style.css', '/vendor/micron-parser-go/parser.wasm'])
def test_only_bundled_frame_resources_are_public(path):
    assert public_frame_resource(path)


@pytest.mark.parametrize('path', ['/api/v1/config', '/ws', '/', '/assets/../api/v1/config',
    '/assets/./config', '/vendor/private/key', '/nomad-crash-tab.html/extra',
    '/Library/Application Support/identity', '/assets/secret\x00.js'])
def test_private_routes_and_traversal_never_receive_opaque_cors(path):
    assert not public_frame_resource(path)


def test_renderer_csp_keeps_opaque_origin_without_remote_media_or_privileged_frames():
    policy = build_nomad_crash_tab_csp('127.0.0.1:55444')
    directives = {part.split()[0]: part.split()[1:] for part in policy.split(';') if part.strip()}
    for name in ('default-src', 'worker-src', 'media-src', 'frame-src', 'object-src', 'base-uri', 'form-action'):
        assert directives[name] == ["'none'"]
    for name in ('script-src', 'style-src', 'img-src', 'font-src', 'connect-src'):
        assert 'http://127.0.0.1:55444' in directives[name]
        assert '*' not in directives[name] and 'http:' not in directives[name] and 'https:' not in directives[name]
    assert "'unsafe-inline'" not in directives['script-src']
    assert "'wasm-unsafe-eval'" in directives['script-src']

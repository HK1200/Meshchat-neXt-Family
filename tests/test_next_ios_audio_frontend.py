"""Execute the exact pinned voice-player backport with real Blob URLs."""

from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ios/NextRuntimeProbe"))
import audio_frontend  # noqa: E402 - runtime wrappers are outside the test package


def test_actual_pinned_player_uses_wav_and_preserves_ogg_with_size_checks(tmp_path):
    original = (ROOT / "tests/fixtures/next-021-opus-player.js.txt").read_text().strip()
    patched = audio_frontend.rewrite(original)
    script = tmp_path / "player.cjs"
    script.write_text(
        """
const assert = require('node:assert/strict');
const ao=(bytes,max)=>{if(bytes.length>max)throw Error('bounded');return bytes;};
const player={"""
        + patched
        + """};
(async()=>{
 const wav=Buffer.alloc(32044);wav.write('RIFF',0);wav.write('WAVE',8);
 const url=await player.decodeOpusAudioToBlobUrl(wav);
 const response=await fetch(url);
 assert.equal(response.headers.get('content-type'),'audio/wav');
 assert.deepEqual(Buffer.from(await response.arrayBuffer()),wav);URL.revokeObjectURL(url);
 const ogg=Buffer.from('OggS OpusHead');
 const opus=await player.decodeOpusAudioToBlobUrl(ogg);
 assert.equal((await fetch(opus)).headers.get('content-type'),'audio/ogg');URL.revokeObjectURL(opus);
 assert.equal(await player.decodeOpusAudioToBlobUrl(Buffer.alloc(2097153)),null);
 const big=Buffer.alloc(8388653);big.write('RIFF',0);big.write('WAVE',8);
 assert.equal(await player.decodeOpusAudioToBlobUrl(big),null);
 console.log('Exact pinned Opus/WAV player and byte limits passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
    )
    result = subprocess.run(
        ["node", str(script)], capture_output=True, text=True, timeout=15
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_changed_or_duplicate_player_is_rejected():
    original = (ROOT / "tests/fixtures/next-021-opus-player.js.txt").read_text()
    for payload in ("changed frontend", original + original):
        with pytest.raises(ValueError):
            audio_frontend.rewrite(payload)

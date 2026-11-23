# SPDX-License-Identifier: 0BSD
"""Send the pinned archive export to iOS's bounded native download handler."""
import hashlib
from pathlib import Path

CHUNK = 'assets/ArchivesPage-BFi31667.js'
SHA256 = 'ca68c56fa33f7fbd132a3fcee8909531d4c548d411b0569a65ba356e240cca6f'
BEFORE = 'const t=await function(...e){return window.api.get(m("/nomadnet/archives/export"),...e)}({params:e,responseType:"blob"}),i=(new Date).toISOString().slice(0,19).replace(/[:T]/g,"-");await a.downloadFromApiResponse(t,`meshchatnext-archives-${i}.zip`)'
AFTER = 'await __nextExportArchives(e)'


def rewrite(source):
    if source.count(BEFORE) != 1:
        raise ValueError('The pinned archive export changed; review native downloads')
    helper = Path(__file__).with_name('native-archive-export.mjs').read_text()
    marker = 'export function createNativeArchiveExport'
    if helper.count(marker) != 1:
        raise ValueError('The native archive helper declaration changed')
    return source.replace(BEFORE, AFTER) + '\n' + helper.replace(marker, 'function __nextExportArchives', 1)


def stage(folder):
    path = Path(folder) / CHUNK
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != SHA256:
        raise ValueError('The pinned archive frontend checksum changed')
    path.write_text(rewrite(data.decode()))


if __name__ == '__main__':
    import sys
    stage(sys.argv[1])

# SPDX-License-Identifier: 0BSD
"""Adapt the exact released RNCP page to iOS-selected files and native exports."""
import hashlib
from pathlib import Path

CHUNK = 'assets/RNCPPage-CcD6vyMr.js'
SHA256 = '50a3ad123117493e0b6dd90de7fe0d55313c407518f6b7760a45c79c2912c1c6'
UPLOAD_BEFORE = 'async onWebSendFilePicked(e){const s=e.target.files?.[0];if(e.target.value="",!s||this.importInProgress||this.sendInProgress)return;if(!s.size||s.size>this.importLimit)return void(this.importError=this.$t("rncp.import_size_limit",{mib:Math.floor(this.importLimit/1048576)}));const t=new AbortController;this.importController=t,this.importInProgress=!0,this.importError=null;try{const e=new FormData;e.append("file",s);const i=await function(e,...s){return window.api.post(p("/rncp/upload"),e,...s)}(e,{signal:t.signal,timeout:0});if(this.importsDisposed)return;this.sendFilePath=i.data.file_path}catch(i){this.importsDisposed||t.signal.aborted||(this.importError=i.response?.data?.message||this.$t("rncp.import_failed"))}finally{this.importsDisposed||(this.importInProgress=!1,this.importController=null,await this.loadImportedFiles())}}'
UPLOAD_AFTER = UPLOAD_BEFORE.replace('this.importController=t', 'this.sendFilePath="",this.importController=t')
FILES_BEFORE = 'async openReceiveDirectory(){this.receiveDirectory||await this.syncListenerStatusFromServer(),this.receiveDirectory&&(await o.openDirectoryOrCopy(this.receiveDirectory,()=>a.success(this.$t("common.copied")))||t.alert(this.receiveDirectory))}'
FILES_AFTER = 'async openReceiveDirectory(){try{await __nextShowRNCPFiles()}catch(e){await t.alert(e.response?.data?.message||e.message||"Could not load received files.")}}'
SAVE_BEFORE = 'async pickFetchSaveDirectory(){const e=await o.pickDirectory();if(e)return void(this.fetchSavePath=e);if(o.isElectron())return;const s=await t.prompt(this.$t("rncp.web_save_path_prompt"));null!=s&&String(s).trim()&&(this.fetchSavePath=String(s).trim())}'
SAVE_AFTER = 'async pickFetchSaveDirectory(){await this.syncListenerStatusFromServer();this.fetchSavePath=this.receiveDirectory||null;await t.alert("Fetched files are saved in Received files. Open that folder to share or save a copy.")}'

SEND_AFTER = 'timeout:this.sendTimeout,no_compress:this.sendNoCompress},{timeout:0})'
FETCH_AFTER = 'save_path:this.fetchSavePath||null,allow_overwrite:this.fetchAllowOverwrite},{timeout:0})'


def rewrite(source):
    for marker in (SEND_AFTER, FETCH_AFTER):
        if source.count(marker) != 1: raise ValueError("The released RNCP transfer-lifetime protection changed")
    for before, after in ((UPLOAD_BEFORE, UPLOAD_AFTER), (FILES_BEFORE, FILES_AFTER), (SAVE_BEFORE, SAVE_AFTER)):
        if source.count(before) != 1: raise ValueError('The pinned RNCP file controls changed; review native file handling')
        source = source.replace(before, after)
    return source + '\n' + Path(__file__).with_name('native-rncp-files.mjs').read_text()


def stage(folder):
    path = Path(folder) / CHUNK
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != SHA256: raise ValueError('The pinned RNCP frontend checksum changed')
    path.write_text(rewrite(data.decode()))


if __name__ == '__main__':
    import sys
    stage(sys.argv[1])

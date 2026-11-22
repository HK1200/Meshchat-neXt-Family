# SPDX-License-Identifier: 0BSD
"""Adapt the exact released RNCP page to iOS-selected files and native exports."""
import hashlib
from pathlib import Path

CHUNK = 'assets/RNCPPage-CL36DXE1.js'
SHA256 = '7203de41da753b92f91de15dc69d9a1aa8302a284f358b8c5f1568153049a502'
UPLOAD_BEFORE = 'onWebSendFilePicked(e){const t=e.target.files?.[0];e.target.value="",t&&(this.sendFilePath="",s.alert(this.$t("rncp.web_path_hint")))}'
UPLOAD_AFTER = '''async onWebSendFilePicked(e){const t=e.target.files?.[0];e.target.value="";if(!t)return;this.sendFilePath="";this.sendInProgress=true;try{const f=new FormData();f.append("file",t,t.name);const r=await window.api.post("/api/v1/preview/rncp/upload",f,{headers:{"Content-Type":undefined},timeout:0});if(typeof r.data.file_path!=="string")throw new Error("Could not import the selected file.");this.sendFilePath=r.data.file_path}catch(x){await s.alert(x.response?.data?.message||x.message||"Could not import the selected file.")}finally{this.sendInProgress=false}}'''
FILES_BEFORE = 'async openReceiveDirectory(){this.receiveDirectory||await this.syncListenerStatusFromServer(),this.receiveDirectory&&(await l.openDirectoryOrCopy(this.receiveDirectory,()=>c.success(this.$t("common.copied")))||s.alert(this.receiveDirectory))}'
FILES_AFTER = 'async openReceiveDirectory(){try{await __nextShowRNCPFiles()}catch(e){await s.alert(e.response?.data?.message||e.message||"Could not load received files.")}}'
SAVE_BEFORE = 'async pickFetchSaveDirectory(){const e=await l.pickDirectory();if(e)return void(this.fetchSavePath=e);if(l.isElectron())return;const t=await s.prompt(this.$t("rncp.web_save_path_prompt"));null!=t&&String(t).trim()&&(this.fetchSavePath=String(t).trim())}'
SAVE_AFTER = 'async pickFetchSaveDirectory(){await this.syncListenerStatusFromServer();this.fetchSavePath=this.receiveDirectory||null;await s.alert("Fetched files are saved in Received files. Open that folder to share or save a copy.")}'

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

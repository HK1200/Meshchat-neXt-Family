// SPDX-License-Identifier: 0BSD
// A local received-file chooser; names are text, never executable markup.
async function __nextShowRNCPFiles() {
    const response = await window.api.get('/api/v1/preview/rncp/files');
    const files = response.data?.files;
    if (!Array.isArray(files)) throw new Error('The received file list could not be loaded.');
    document.getElementById('next-rncp-files')?.remove();
    const previousFocus = document.activeElement;
    const shade = document.createElement('div');
    shade.id = 'next-rncp-files';
    Object.assign(shade.style, {position:'fixed', inset:'0', zIndex:'10000', background:'rgba(0,0,0,.6)', display:'grid', placeItems:'center', padding:'16px'});
    const panel = document.createElement('section');
    panel.setAttribute('role','dialog'); panel.setAttribute('aria-modal','true'); panel.setAttribute('aria-labelledby','next-rncp-files-title');
    Object.assign(panel.style, {background:'var(--mc-surface, #16161b)', color:'var(--mc-text, #eee)', padding:'20px', borderRadius:'16px', width:'min(560px,100%)', maxHeight:'80vh', overflow:'auto'});
    const title = document.createElement('h2'); title.id='next-rncp-files-title'; title.textContent='Received files';
    const close = document.createElement('button'); close.type='button'; close.textContent='Done';
    Object.assign(close.style, {padding:'12px', minHeight:'44px', float:'right'});
    close.addEventListener('click',()=>{shade.remove();previousFocus?.focus();});
    panel.append(close,title);
    if (files.length === 0) {
        const empty = document.createElement('p'); empty.textContent='No files received yet.'; panel.append(empty);
    }
    for (const file of files) {
        if (!file || !/^[a-f0-9]{32}$/.test(file.id) || typeof file.name !== 'string') continue;
        const link = document.createElement('a');
        link.href='/api/v1/preview/rncp/files/'+file.id+'/download'; link.download=file.name;
        link.textContent=file.name;
        Object.assign(link.style,{display:'block',padding:'14px 0',overflowWrap:'anywhere',textDecoration:'underline',color:'var(--mc-accent, #60a5fa)'});
        panel.append(link);
    }
    shade.append(panel); document.body.append(shade); close.focus();
}

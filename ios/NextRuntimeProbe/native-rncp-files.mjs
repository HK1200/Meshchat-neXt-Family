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
    Object.assign(close.style, {padding:'12px', minHeight:'44px', float:'right', border:'1px solid var(--mc-border, #555)', borderRadius:'8px', background:'transparent', color:'inherit'});
    close.addEventListener('click',()=>{shade.remove();previousFocus?.focus();});
    const status = document.createElement('p'); status.setAttribute('role','status'); status.setAttribute('aria-live','polite');
    const refresh = document.createElement('button'); refresh.type='button'; refresh.textContent='Refresh';
    Object.assign(refresh.style,{padding:'12px',minHeight:'44px',border:'1px solid var(--mc-border, #555)',borderRadius:'8px',background:'transparent',color:'inherit'});
    refresh.addEventListener('click',async()=>{
        refresh.disabled=true;
        try { await __nextShowRNCPFiles(); }
        catch(error) { status.textContent=error.response?.data?.message||'The file list could not be refreshed.'; refresh.disabled=false; }
    });
    panel.append(close,title,refresh,status);
    if (files.length === 0) {
        const empty = document.createElement('p'); empty.textContent='No files received yet.'; panel.append(empty);
    }
    for (const file of files) {
        if (!file || !/^[a-f0-9]{32}$/.test(file.id) || typeof file.name !== 'string') continue;
        const link = document.createElement('a');
        link.href='/api/v1/preview/rncp/files/'+file.id+'/download'; link.download=file.name;
        link.textContent=file.name;
        Object.assign(link.style,{display:'block',padding:'14px 0',overflowWrap:'anywhere',textDecoration:'underline',color:'var(--mc-accent, #60a5fa)'});
        const row = document.createElement('div');
        Object.assign(row.style,{display:'grid',gridTemplateColumns:'minmax(0,1fr) auto',alignItems:'center',gap:'8px',padding:'8px 0',borderBottom:'1px solid var(--mc-border, #555)'});
        const remove = document.createElement('button'); remove.type='button'; remove.textContent='Remove';
        Object.assign(remove.style,{padding:'12px',minHeight:'44px',border:'1px solid currentColor',borderRadius:'8px',color:'var(--mc-danger, #ef4444)'});
        remove.disabled=file.in_use===true;
        if(remove.disabled) remove.title='File in use. Refresh after the transfer finishes.';
        remove.addEventListener('click',()=>{
            remove.disabled=true;
            const confirmation=document.createElement('div'); Object.assign(confirmation.style,{gridColumn:'1 / -1',paddingBottom:'12px'});
            const question=document.createElement('p'); question.textContent='Remove this received file from neXt? Copies you saved outside neXt are kept.';
            const cancel=document.createElement('button'); cancel.type='button'; cancel.textContent='Keep file';
            const confirm=document.createElement('button'); confirm.type='button'; confirm.textContent='Remove file';
            for(const button of [cancel,confirm]) Object.assign(button.style,{padding:'12px',minHeight:'44px',border:'1px solid var(--mc-border, #555)',borderRadius:'8px',background:'transparent',color:'inherit'});
            Object.assign(confirm.style,{background:'#b91c1c',color:'#fff',border:'1px solid #b91c1c',borderRadius:'8px',marginInlineStart:'8px'});
            cancel.addEventListener('click',()=>{confirmation.remove();remove.disabled=false;remove.focus();});
            confirm.addEventListener('click',async()=>{
                confirm.disabled=true;cancel.disabled=true;status.textContent='';
                try {
                    const result=await window.api.delete('/api/v1/preview/rncp/files/'+file.id);
                    if(result.status!==204) throw new Error('File removal was not confirmed.');
                    row.remove();status.textContent='File removed.';refresh.focus();
                } catch(error) {
                    status.textContent=error.response?.data?.message||'The file could not be removed. Refresh and try again.';
                    confirm.disabled=false;cancel.disabled=false;
                }
            });
            confirmation.append(question,cancel,confirm);row.append(confirmation);cancel.focus();
        });
        row.append(link,remove);
        if(file.in_use===true){const active=document.createElement('span');active.textContent='In use. Refresh after the transfer finishes.';active.style.gridColumn='1 / -1';row.append(active);}
        panel.append(row);
    }
    shade.append(panel); document.body.append(shade); close.focus();
}

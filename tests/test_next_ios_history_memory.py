

def test_attachment_pages_keep_memory_bounded_and_original_files_available(tmp_path):
    import base64
    import sys
    import tracemalloc
    from pathlib import Path
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'ios/NextRuntimeProbe'))
    from loopback_probe import ConversationHistory
    peer='ab'*16
    history=ConversationHistory(tmp_path/'history.sqlite3')
    encoded=base64.b64encode(b'x'*1_000_000).decode()
    for index in range(20):
        history.save(peer,dict(hash=f'{index+1:064x}',source_hash=peer,destination_hash='cd'*16,
            state='received',content='Synthetic attachment',is_outbound=False,
            fields={'file_attachments':[{'file_name':'private-fixture.bin','file_size':1_000_000,'file_bytes':encoded}]}))
    tracemalloc.start()
    try:
        page=history.page(peer,{'count':100})
        _,peak=tracemalloc.get_traced_memory()
    finally:tracemalloc.stop()
    assert peak < 16_000_000, f'Chat pages allocated {peak} bytes instead of bounded metadata'
    assert len(page)==20
    assert all(row['fields']['file_attachments'][0]['file_bytes'] is None for row in page)
    assert history.message(f'{1:064x}')['fields']['file_attachments'][0]['file_bytes']==encoded
    history.close()

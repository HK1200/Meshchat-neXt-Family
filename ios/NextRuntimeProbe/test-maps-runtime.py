"""Private HTTP proof of the actual pinned map service; no map/network downloads."""
import argparse, asyncio, hashlib, json, multiprocessing, os, sqlite3, sys
from contextlib import ExitStack
from pathlib import Path
from urllib.request import Request, urlopen

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'tests'),str(ROOT/'ios/NextRuntimeProbe'),str(ROOT/'app/src/main/python')]
if os.environ.get("NEXT_MAP_BACKEND"): sys.path.insert(0,os.environ["NEXT_MAP_BACKEND"])
from test_next_ios_tcp_integration import api,backend,start,wait,SESSIONS,private_request


def server(folder,ready,settings,pipe):
    import importlib.abc
    class NoDesktopImports(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname in ('psutil', 'meshchatnext.src.backend.http.routes.app_info'):
                raise ModuleNotFoundError('Desktop module must not load in the mobile map runtime: '+fullname)
            return None
    sys.meta_path.insert(0,NoDesktopImports())
    from loopback_probe import serve
    from map_runtime import MapRuntime
    frontend=folder/'frontend';frontend.mkdir(exist_ok=True)
    (frontend/'index.html').write_text('<html>Private map test</html>')
    asyncio.run(serve(ready,frontend,settings,device=True,map_factory=MapRuntime))



def map_hub(folder,port,pipe):
    import RNS
    from map_runtime import MapRuntime
    folder.mkdir()
    (folder/'config').write_text('[reticulum]\nshare_instance = No\nenable_transport = No\n[interfaces]\n[[Private map exchange]]\ntype = TCPServerInterface\nenabled = Yes\nlisten_ip = 127.0.0.1\nlisten_port = '+str(port)+'\n')
    rns=RNS.Reticulum(configdir=str(folder),loglevel=1)
    service=MapRuntime(folder,RNS.Identity(),rns,lambda event:None)
    service.config.map_data_display_name.set('Private map catalog')
    service.map_data_manager.start()
    data=json.dumps({'type':'FeatureCollection','features':[{'type':'Feature','geometry':{'type':'Point','coordinates':[-122,48]},'properties':{'name':'Synthetic private marker'}}]}).encode()
    published=service.map_data_manager.publish_bytes(data,name='Private marker',hinted_format='geojson')['map']
    info=service.map_data_manager.status()
    pipe.send(dict(destination=info['destination_hash'],map_id=published['map_id'],sha256=published['sha256']))
    try:
        while pipe.recv()=='announce':service.map_data_manager.announce()
    finally:
        service.map_data_manager.stop();service.database.provider.close_all()


def upload(base,token,name,data):
    from urllib.parse import urlsplit
    from urllib.error import HTTPError
    boundary='next-private-map-boundary'
    body=(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode()+data+f'\r\n--{boundary}--\r\n'.encode())
    origin='http://'+urlsplit(base).netloc
    request=Request(origin+'/api/v1/map/offline',data=body,headers={
        'X-neXt-Session':SESSIONS[urlsplit(base).netloc], 'Origin':origin,'X-CSRF-Token':token,
        'Content-Type':'multipart/form-data; boundary='+boundary})
    try:
        with urlopen(request,timeout=30) as response:return response.status,json.load(response)
    except HTTPError as error:return error.code,error.read().decode()


def main(folder):
    folder.mkdir(mode=0o700,parents=True,exist_ok=False)
    app=folder/'preview';app.mkdir()
    settings=app/'settings.json'
    from meshchatnext.src.backend.map_starter_mbtiles import solid_png_rgba
    pixel=solid_png_rgba(1,1,(22,66,99,255))
    fixture=folder/'fixture.mbtiles'
    with sqlite3.connect(fixture) as db:
        db.execute('CREATE TABLE metadata(name TEXT,value TEXT)')
        db.executemany('INSERT INTO metadata VALUES (?,?)',[('name','Private detail map'),('format','png'),('minzoom','9'),('maxzoom','9')])
        db.execute('CREATE TABLE tiles(zoom_level INTEGER,tile_column INTEGER,tile_row INTEGER,tile_data BLOB)')
        db.execute('INSERT INTO tiles VALUES(9,1,510,?)',(pixel,))
        # Map files are not message attachments: exercise a valid upload larger
        # than the runtime's ordinary 14 MB JSON request ceiling.
        db.execute('INSERT INTO metadata VALUES(?,?)',('bounded-note','x'*2000000))
        for x in range(3,35): db.execute('INSERT INTO tiles VALUES(9,?,510,?)',(x,pixel))
        # This row lies outside import validation's first 32 samples.
        db.execute('INSERT INTO tiles VALUES(9,40,510,?)',(pixel+bytes(2097153),))
        db.execute('CREATE TABLE padding(data BLOB)')
        db.execute('INSERT INTO padding VALUES(zeroblob(15000000))')
    data=fixture.read_bytes();saved_map=None;original_identity=None;descriptor_growth=None
    with ExitStack() as stack:
        import socket
        with socket.socket() as listener:
            listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
        _,hub=start(stack,map_hub,folder/'private-map-hub',port)
        assert hub.poll(15)
        published=hub.recv()
        settings.write_text(json.dumps({'peers':[dict(id='private-map',host='127.0.0.1',port=port,enabled=True)]}))
        with ExitStack() as first:
            ready=app/'first.url';worker,_=start(first,server,app,ready,settings);wait(ready.exists);base=backend(ready)
            original_identity=(app/'reticulum/identity').read_bytes()
            token=api(base,'auth/csrf')[1]['csrf_token']
            wait(lambda:any(row['online'] for row in api(base,'preview/reticulum-connections')[1]['peers']))
            assert api(base,'config')[1]['config']['announce_store_map_data'] is False
            assert api(base,'config',body={'announce_store_map_data':True},method='PATCH',token=token)[0]==200
            hub.send('announce')
            heard=wait(lambda:api(base,'map/data/heard')[1]['announces'])
            assert heard[0]['destination_hash']==published['destination'] and heard[0]['map_name']=='Private map catalog'
            status,catalog=api(base,'map/data/catalog',body={'destination_hash':published['destination']},token=token)
            assert status==200 and catalog['maps'][0]['id']==published['map_id'],(status,catalog)
            status,fetched=api(base,'map/data/fetch',body={'destination_hash':published['destination'],'map_id':published['map_id']},token=token)
            import base64
            assert status==200 and hashlib.sha256(base64.b64decode(fetched['data_b64'])).hexdigest()==published['sha256'],(status,fetched)
            assert api(base,'map/offline')[0]==200
            assert api(base,'map/mbtiles')[0]==200
            assert api(base,'map/drawings',body={'name':'No permission','data':'{}'})[0]==403
            assert api(base,'config',body={'map_default_zoom':9,'map_coordinate_format':'olc'},method='PATCH',token=token)[0]==200
            for value in (99,True,'9'):
                assert api(base,'config',body={'map_default_zoom':value},method='PATCH',token=token)[0]==400
            for value in ('nan','181','-181'):
                assert api(base,'config',body={'map_default_lon':value},method='PATCH',token=token)[0]==400
            assert api(base,'config',body={'map_mbtiles_dir':'/tmp/escape'},method='PATCH',token=token)[0]==400
            assert api(base,'config')[1]['config']['map_default_zoom']==9
            status,result=upload(base,token,'private.mbtiles',data)
            assert status==200,(status,result)
            assert len(result['metadata']['bounded-note'])==2048,'Imported metadata reads must stay bounded'
            saved_map=Path(result['metadata']['path']);assert saved_map.is_relative_to(app/'map-tools/maps')
            assert saved_map.read_bytes()==data
            # TMS row 510 corresponds to XYZ y=1 at z9.
            with urlopen(private_request(base,'/api/v1/map/tiles/9/1/1.png')) as response:
                assert response.read()==pixel and response.headers['Content-Type']=='image/png'
            from meshchatnext.src.backend.map_manager import TRANSPARENT_TILE
            with urlopen(private_request(base,'/api/v1/map/tiles/9/40/1.png')) as response:
                assert response.read()==TRANSPARENT_TILE,'Oversized unsampled tile must not be loaded into the response'
            # The reported map descriptor leak must not return in this port.
            descriptors=Path('/proc')/str(worker.pid)/'fd'
            if descriptors.is_dir():
                before=len(list(descriptors.iterdir()))
                for _ in range(300):
                    with urlopen(private_request(base,'/api/v1/map/tiles/9/1/1.png')) as response:
                        assert response.read()==pixel
                descriptor_growth=len(list(descriptors.iterdir()))-before
                assert descriptor_growth<=8,descriptor_growth
            for tile in ('99/0/0','9/-1/1','9/512/1'):
                assert api(base,'map/tiles/'+tile)[0]==400
            digest=hashlib.sha256(saved_map.read_bytes()).hexdigest()
            assert upload(base,token,'private.mbtiles',b'invalid sqlite')[0]==400
            assert hashlib.sha256(saved_map.read_bytes()).hexdigest()==digest
            assert api(base,'map/offline')[1]['path']==str(saved_map)
            # Same filename, new valid map: preserve the old one as well.
            second=upload(base,token,'private.mbtiles',data)
            assert second[0]==200 and second[1]['metadata']['path']!=str(saved_map)
            assert saved_map.read_bytes()==data
            assert not list((app/'map-tools/maps').glob('import-*.tmp'))
            assert api(base,'map/drawings',body={'name':'Private marker','data':'{"type":"FeatureCollection","features":[]}'},token=token)[0]==200
            drawings=api(base,'map/drawings')[1]['drawings'];assert len(drawings)==1
            assert api(base,'map/overlays')[0]==200
            assert api(base,'map/mbtiles/regional-download')[1]['status']=='idle'
        ready=app/'second.url';start(stack,server,app,ready,settings);wait(ready.exists);base=backend(ready)
        assert (app/'reticulum/identity').read_bytes()==original_identity
        assert api(base,'config')[1]['config']['map_default_zoom']==9
        assert len(api(base,'map/drawings')[1]['drawings'])==1
        assert api(base,'telephone/contacts')[1]['contacts']==[]
        assert api(base,'lxmf/conversations')[1]['conversations']==[]
        token=api(base,'auth/csrf')[1]['csrf_token']
        assert api(base,'map/mbtiles/'+saved_map.name,body={},method='DELETE',token=token)[0]==200
        assert not saved_map.exists()
        assert Path(api(base,'map/offline')[1]['path']).is_file()
    proof={'ok':True,'public_network':False,'automatic_downloads':False,'private_http':True,'signed_map_discovery_and_reticulum_catalog_transfer':True,
           'native_identity_unchanged':True,'valid_import_and_tiles':True,'map_upload_exceeded_message_body_limit':len(data)>14_000_000,'invalid_import_preserved_active_map':True,
           'duplicate_import_preserved_existing_maps':True,'settings_and_drawings_survived_restart':True,
           'deleting_one_map_preserved_other_maps':True,'csrf_required':True,'metadata_and_unsampled_tile_reads_bounded':True,'tile_read_descriptor_growth_after_300_reads':descriptor_growth}
    (folder/'proof.json').write_text(json.dumps(proof,indent=2)+'\n');print(json.dumps(proof))

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--work-dir',type=Path,required=True)
    parser.add_argument("--backend-source",type=Path,required=True)
    args=parser.parse_args()
    os.environ["NEXT_MAP_BACKEND"]=str(args.backend_source.resolve());sys.path.insert(0,os.environ["NEXT_MAP_BACKEND"])
    main(args.work_dir.resolve())

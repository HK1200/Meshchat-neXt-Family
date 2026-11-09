"""App-private raster MBTiles packs. No network or executable map content."""
import contextlib,json,re,sqlite3,time,uuid
from pathlib import Path
from urllib.parse import quote

def image_type(data):
    if data.startswith(b'\x89PNG\r\n\x1a\n'):return 'image/png'
    if data.startswith(b'\xff\xd8\xff'):return 'image/jpeg'
    if data.startswith(b'RIFF') and data[8:12]==b'WEBP':return 'image/webp'
    raise ValueError('This pack needs raster PNG, JPEG or WebP tiles; vector/PBF packs are not supported yet')

class MapStore:
    def __init__(self,root,state,lock,save):
        self.root=Path(root)/'maps';self.root.mkdir(exist_ok=True);self.state=state;self.lock=lock;self.save=save;state.setdefault('map_packs',[]);state.setdefault('active_map',state['map_packs'][-1]['id'] if state['map_packs'] else 'pnw')
    def connection(self,path):
        db=sqlite3.connect('file:'+quote(str(path))+'?mode=ro&immutable=1',uri=True);disable_loader=getattr(db,'enable_load_extension',None)
        if disable_loader is not None:disable_loader(False)
        # Android omits the extension-loader API entirely. Also enforce a
        # read/function allowlist so extensions, writes and ATTACH stay denied.
        allowed_functions={'substr','length','min','max'}
        db.set_authorizer(lambda action,arg1,arg2,database,origin:sqlite3.SQLITE_OK if action in [sqlite3.SQLITE_SELECT,sqlite3.SQLITE_READ] or (action==sqlite3.SQLITE_FUNCTION and str(arg2).lower() in allowed_functions) else sqlite3.SQLITE_DENY)
        db.setlimit(sqlite3.SQLITE_LIMIT_LENGTH,4*1024**2)
        deadline=time.monotonic()+10;db.set_progress_handler(lambda:1 if time.monotonic()>deadline else 0,10000);return contextlib.closing(db)
    def install(self,source,name):
        source=Path(source).resolve()
        if source.parent!=self.root.resolve() or not source.name.startswith('import-') or source.suffix!='.tmp':raise ValueError('Invalid map import path')
        try:
            if source.stat().st_size>2*1024**3:raise ValueError('Choose a map smaller than 2 GB')
            with source.open('rb') as stream:
                if stream.read(16)!=b'SQLite format 3\x00':raise ValueError('Not an MBTiles database')
            with self.connection(source) as db:
                metadata=dict(db.execute('SELECT substr(name,1,128),substr(value,1,2048) FROM metadata LIMIT 100'))
                if metadata.get('format','').lower() in ['pbf','mvt']:raise ValueError('Choose a raster PNG/JPEG/WebP MBTiles pack')
                rows=db.execute('SELECT zoom_level,tile_column,tile_row,substr(tile_data,1,16),length(tile_data) FROM tiles LIMIT 32').fetchall()
                if not rows:raise ValueError('Map contains no tiles')
                for z,x,y,data,size in rows:
                    if any(type(v) is not int for v in [z,x,y]) or not 0<=z<=20 or not 0<=x<2**z or not 0<=y<2**z or not isinstance(data,bytes) or size>2*1024**2:raise ValueError('Invalid map tile')
                    image_type(data)
                low,high=db.execute('SELECT MIN(zoom_level),MAX(zoom_level) FROM tiles').fetchone()
                if not 0<=low<=high<=20:raise ValueError('Unsupported map zoom range')
            with self.lock:
                if len(self.state['map_packs'])>=12:raise ValueError('Remove an imported map before adding another')
                key=uuid.uuid4().hex;target=self.root/(key+'.mbtiles');record={'id':key,'name':str(metadata.get('name') or name or 'Offline map')[:80],'minZoom':low,'maxZoom':high,'size':source.stat().st_size,'center':None}
                try:
                    center=[float(v) for v in str(metadata.get('center','')).split(',')]
                    if len(center)>=2 and -180<=center[0]<=180 and -85<=center[1]<=85:record['center']={'lat':center[1],'lon':center[0]}
                except Exception:pass
                source.replace(target);self.state['map_packs'].append(record);self.save()
            return record
        except Exception:
            source.unlink(missing_ok=True);raise
    def snapshot(self):
        with self.lock:return [dict(pack) for pack in self.state['map_packs']]
    def tile(self,key,z,x,y):
        if not re.fullmatch('[a-f0-9]{32}',str(key)) or any(type(v) is not int for v in [z,x,y]) or not 0<=z<=20 or not 0<=x<2**z or not 0<=y<2**z:return None
        with self.lock:
            if not any(p['id']==key for p in self.state['map_packs']):return None
        try:
            with self.connection(self.root/(key+'.mbtiles')) as db:row=db.execute('SELECT substr(tile_data,1,2097153) FROM tiles WHERE zoom_level=? AND tile_column=? AND tile_row=? LIMIT 1',(z,x,2**z-1-y)).fetchone()
            if not row or len(row[0])>2*1024**2:return None
            return {'mime':image_type(row[0]),'bytes':row[0]}
        except Exception:return None
    def select(self,key):
        with self.lock:
            if key!='pnw' and not any(p['id']==key for p in self.state['map_packs']):raise ValueError('Unknown map region')
            self.state['active_map']=key;self.save()
    def source(self,z,x,y):
        with self.lock:key=self.state['active_map'];pack=next((p for p in self.state['map_packs'] if p['id']==key),None)
        if pack and pack['minZoom']<=z<=pack['maxZoom'] and self.tile(key,z,x,y):return 'offline-tiles/'+key+'/'+str(z)+'/'+str(x)+'/'+str(y)
        return ''
    def remove(self,key):
        with self.lock:
            if not any(p['id']==key for p in self.state['map_packs']):raise ValueError('Unknown imported map')
            self.state['map_packs']=[p for p in self.state['map_packs'] if p['id']!=key]
            if self.state['active_map']==key:self.state['active_map']='pnw'
            self.save();(self.root/(key+'.mbtiles')).unlink(missing_ok=True)

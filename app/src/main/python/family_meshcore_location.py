"""Family v1 location frames in encrypted MeshCore DIRECT chat only.

The geo URI remains readable in other clients. Family interprets the versioned
frame as a map update after checking peer identity and guardian permission.
"""
import re
from family_location import valid_fix
PREFIX='!NFLOC1:'
FRAME=re.compile(r'!NFLOC1:geo:(-?\d+\.\d{7}),(-?\d+\.\d{7}),(-?\d+\.\d{2});u=(\d+\.\d{2});t=(\d{1,10});s=(\d+\.\d{2});b=(\d+\.\d{2})')
def encode(fix):
    f=valid_fix(fix)
    text=f"{PREFIX}geo:{f['latitude']:.7f},{f['longitude']:.7f},{f['altitude']:.2f};u={f['accuracy']:.2f};t={int(f['last_update'])};s={f['speed']:.2f};b={f['bearing']:.2f}"
    if len(text)>160:raise ValueError('Location frame is too large')
    return text

def decode(text):
    if not isinstance(text,str) or len(text)>160:raise ValueError('Invalid private location frame')
    match=FRAME.fullmatch(text)
    if not match:raise ValueError('Invalid private location frame')
    lat,lon,alt,accuracy,stamp,speed,bearing=match.groups()
    return valid_fix(dict(latitude=float(lat),longitude=float(lon),altitude=float(alt),accuracy=float(accuracy),last_update=int(stamp),speed=float(speed),bearing=float(bearing)))

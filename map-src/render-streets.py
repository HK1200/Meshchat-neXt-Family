"""Render an offline Protomaps cutout, with named streets at closer zooms."""
import argparse
import gzip
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import mapbox_vector_tile
from PIL import Image, ImageDraw, ImageFont
from pmtiles.reader import MmapSource, all_tiles

LAND = "#f3efe5"
FONT = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 10)
ROADS = {
    "path": ("#b6a28e", "#f7f5ea", 1),
    "minor_road": ("#b7ae9f", "#ffffff", 2),
    "major_road": ("#b09b75", "#fff4d4", 3),
    "highway": ("#bd8b4f", "#ffdfa8", 4),
}

def render(item):
    (zoom, x, y), raw = item
    if raw.startswith(b"\x1f\x8b"):
        raw = gzip.decompress(raw)
    layers = mapbox_vector_tile.decode(raw, default_options={"y_coord_down": True})
    image = Image.new("RGB", (256, 256), "#acd4e6")
    draw = ImageDraw.Draw(image)
    roads, labels = [], []
    for layer in ("earth", "landcover", "landuse", "water", "buildings", "roads", "places"):
        data = layers.get(layer, {})
        scale = 256 / data.get("extent", 4096)
        def points(ring):
            return [(px * scale, py * scale) for px, py in ring]
        for feature in data.get("features", []):
            props = feature["properties"]
            kind = props.get("kind", "")
            geometry = feature.get("geometry") or {}
            typ, coords = geometry.get("type"), geometry.get("coordinates", [])
            if props.get("min_zoom", 0) > zoom:
                continue
            name = props.get("name:en") or props.get("name") or props.get("ref")
            if layer == "roads" and kind in ROADS and typ in ("LineString", "MultiLineString"):
                casing, fill, width = ROADS[kind]
                for line in ([coords] if typ == "LineString" else coords):
                    pixels = points(line)
                    if len(pixels) < 2:
                        continue
                    roads.append((width, pixels, casing, fill))
                    if name and kind != "path" and (zoom >= 15 or width >= 3):
                        segments = sorted(zip(pixels, pixels[1:]),
                            key=lambda p: -((p[0][0]-p[1][0])**2+(p[0][1]-p[1][1])**2))
                        start, end = segments[0]
                        length = ((start[0]-end[0])**2+(start[1]-end[1])**2)**.5
                        if length >= 38:
                            labels.append((6-width, str(name), ((start[0]+end[0])/2,(start[1]+end[1])/2)))
            elif layer == "places" and typ == "Point" and name and kind in ("locality", "neighbourhood"):
                labels.append((0, str(name), points([coords])[0]))
            elif typ in ("Polygon", "MultiPolygon"):
                color = {
                    "earth": LAND, "water": "#acd4e6",
                    "landcover": "#d4e3c3" if kind in ("forest", "wood", "grassland") else None,
                    "landuse": "#dce9cb" if kind in ("park", "nature_reserve", "national_park") else
                               "#ebe7df" if kind in ("residential", "urban_area", "industrial") else None,
                    "buildings": "#dbcec3" if zoom >= 15 else None,
                }.get(layer)
                if color:
                    for polygon in ([coords] if typ == "Polygon" else coords):
                        if polygon:
                            draw.polygon(points(polygon[0]), fill=color)
                            for hole in polygon[1:]:
                                draw.polygon(points(hole), fill=LAND if layer != "earth" else "#acd4e6")
    for width, pixels, casing, fill in sorted(roads, key=lambda row: row[0]):
        draw.line(pixels, fill=casing, width=width+2, joint="curve")
        draw.line(pixels, fill=fill, width=width, joint="curve")

    used, names = [], set()
    for _, name, point in sorted(labels):
        if name in names or len(name) > 38:
            continue
        left, top, right, bottom = box = draw.textbbox(point, name, font=FONT, anchor="mm", stroke_width=1)
        if left < 3 or top < 3 or right > 253 or bottom > 253:
            continue
        if any(not (right+3<a or c+3<left or bottom+2<b or d+2<top) for a,b,c,d in used):
            continue
        draw.text(point, name, fill="#372d26", font=FONT, anchor="mm", stroke_width=1, stroke_fill="#fffdf6")
        names.add(name)
        used.append(box)
    return zoom, x, y, image.quantize(colors=96)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    with args.archive.open("rb") as source, ProcessPoolExecutor(max_workers=4) as pool:
        tiles = (item for item in all_tiles(MmapSource(source)) if 13 <= item[0][0] <= 15)
        for count, (z, x, y, image) in enumerate(pool.map(render, tiles, chunksize=16, buffersize=8), 1):
            folder = args.output / str(z) / str(x)
            folder.mkdir(parents=True, exist_ok=True)
            image.save(folder / (str(y) + ".png"), optimize=False)
    print(f"Rendered {count} licensed offline street tiles")
if __name__ == "__main__":
    main()

import Map from "ol/Map.js";
import View from "ol/View.js";
import Feature from "ol/Feature.js";
import Point from "ol/geom/Point.js";
import TileLayer from "ol/layer/Tile.js";
import VectorLayer from "ol/layer/Vector.js";
import XYZ from "ol/source/XYZ.js";
import VectorSource from "ol/source/Vector.js";
import { defaults as interactions } from "ol/interaction/defaults.js";
import ScaleLine from "ol/control/ScaleLine.js";
import { fromLonLat, toLonLat, transformExtent } from "ol/proj.js";
import Style from "ol/style/Style.js";
import Icon from "ol/style/Icon.js";
import Text from "ol/style/Text.js";
import Fill from "ol/style/Fill.js";
import Stroke from "ol/style/Stroke.js";

const coordinate = ({ lat, lon }) => fromLonLat([lon, lat]);

function pinStyle(feature) {
    const { name, stale, selected } = feature.getProperties();
    const fill = selected ? "#116d67" : "#d3e9eb";
    const ink = selected ? "#fff" : "#1b5257";
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="40" height="40" viewBox="0 0 40 40"><path d="M4 3h32v22H25l-5 9-5-9H4Z" fill="${fill}" stroke="${selected ? "#fff" : ink}" stroke-width="2" ${stale ? 'stroke-dasharray="3 2"' : ""}/><circle cx="20" cy="14" r="4" fill="${ink}"/></svg>`;
    return new Style({
        image: new Icon({ src: "data:image/svg+xml," + encodeURIComponent(svg), anchor: [0.5, 0.85] }),
        text: new Text({
            text: name,
            offsetY: 14,
            font: "600 13px system-ui",
            fill: new Fill({ color: "#f8fafc" }),
            stroke: new Stroke({ color: "#10262b", width: 4 }),
        }),
        zIndex: selected ? 1 : 0,
    });
}

export function create({ target, center, zoom, packs, streetTiles, tileIndex, onCamera, onSelect, onSettled }) {
    const overview = new TileLayer({
        preload: 1,
        source: new XYZ({
            minZoom: 5,
            maxZoom: 9,
            tileUrlFunction: ([z, x, y]) => {
                const key = `${z}/${x}/${y}`;
                return tileIndex.has(key) ? `pnw-tiles/${key}.png` : undefined;
            },
        }),
    });
    const layers = [overview];
    for (const pack of packs) {
        layers.push(new TileLayer({
            preload: 1,
            minZoom: pack.minZoom - 0.5,
            source: new XYZ({
                minZoom: pack.minZoom,
                maxZoom: pack.maxZoom,
                url: `offline-tiles/${pack.id}/{z}/{x}/{y}`,
            }),
        }));
    }
    if (streetTiles) {
        const streets = new TileLayer({
            minZoom: 12.5,
            extent: transformExtent([-123.10, 48.55, -121.9, 49.08], "EPSG:4326", "EPSG:3857"),
            source: new XYZ({ minZoom: 13, maxZoom: 15, url: "whatcom-tiles/{z}/{x}/{y}.png" }),
        });
        const moreDetailed = layers.findIndex((layer) => layer.getSource().getTileGrid().getMaxZoom() > 15);
        layers.splice(moreDetailed === -1 ? layers.length : moreDetailed, 0, streets);
    }

    const points = new VectorSource();
    const markers = new VectorLayer({ source: points, declutter: true, style: pinStyle });
    const view = new View({
        center: coordinate(center),
        zoom,
        minZoom: Math.min(5, ...packs.map((pack) => pack.minZoom)),
        maxZoom: 20,
    });
    const map = new Map({
        target,
        view,
        layers: [...layers, markers],
        controls: [new ScaleLine()],
        interactions: interactions({ altShiftDragRotate: false, pinchRotate: false }),
        pixelRatio: Math.min(window.devicePixelRatio || 1, 2),
    });

    function reportCamera() {
        const [lon, lat] = toLonLat(view.getCenter());
        onCamera({ lon, lat }, view.getZoom(), view.getMinZoom(), view.getMaxZoom());
    }
    view.on(["change:center", "change:resolution"], reportCamera);
    map.on("moveend", onSettled);
    map.on("singleclick", (event) => {
        const id = map.forEachFeatureAtPixel(event.pixel, (feature) => feature.getId(), { hitTolerance: 8 });
        if (id !== undefined) onSelect(id);
    });

    return {
        setTarget(nextTarget) {
            map.setTarget(nextTarget);
            reportCamera();
        },
        setPeople(people) {
            points.clear();
            points.addFeatures(people.map((person) => {
                const feature = new Feature({ ...person, geometry: new Point(coordinate(person)) });
                feature.setId(person.id);
                feature.setStyle(pinStyle(feature));
                return feature;
            }));
        },
        recenter(point) {
            view.cancelAnimations();
            view.animate({ center: coordinate(point), duration: 260 });
        },
        zoomBy(delta) {
            const zoom = Math.max(view.getMinZoom(), Math.min(view.getMaxZoom(), view.getZoom() + delta));
            view.cancelAnimations();
            view.animate({ zoom, duration: 200 });
        },
        moving: () => view.getAnimating() || view.getInteracting(),
        dispose() {
            view.cancelAnimations();
            map.dispose();
        },
    };
}

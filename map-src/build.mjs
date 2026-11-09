// Use the OpenLayers and Vite versions already installed for meshchat neXt.
import { fileURLToPath } from "node:url";
import { build } from "../../meshchat-next/node_modules/vite/dist/node/index.js";

const path = (relative) => fileURLToPath(new URL(relative, import.meta.url));

await build({
    configFile: false,
    publicDir: false,
    resolve: {
        alias: [{ find: /^ol\//, replacement: path("../../meshchat-next/node_modules/ol/") }],
    },
    build: {
        lib: {
            entry: path("./family-map.js"),
            name: "FamilyMap",
            formats: ["iife"],
            fileName: () => "family-map.js",
        },
        outDir: path("../app/src/main/assets/"),
        emptyOutDir: false,
        target: "chrome100",
    },
});

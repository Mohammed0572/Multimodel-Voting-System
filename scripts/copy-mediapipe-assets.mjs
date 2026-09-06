// Copy the WASM runtime bundled in @mediapipe/tasks-vision into public assets.
import { existsSync, mkdirSync, readdirSync, copyFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(scriptDirectory, "..");
const source = path.join(
  projectRoot,
  "node_modules",
  "@mediapipe",
  "tasks-vision",
  "wasm",
);
const destination = path.join(projectRoot, "public", "mediapipe", "wasm");

if (!existsSync(source)) {
  console.warn(
    "[copy-mediapipe-assets] WASM folder not found; run npm install first.",
  );
  process.exit(0);
}

mkdirSync(destination, { recursive: true });
let copied = 0;
for (const entry of readdirSync(source)) {
  copyFileSync(path.join(source, entry), path.join(destination, entry));
  copied += 1;
}

console.log(
  `[copy-mediapipe-assets] Staged ${copied} file(s) into public/mediapipe/wasm`,
);

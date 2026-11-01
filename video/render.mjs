// Node.js render entry for TraceLoop video guides (docs/remotion: plain Node SSR).
// Usage: node render.mjs --bundle <dir> --project <videoDir> --props <json> --out <mp4> --progress <json>
// Bundles on demand into <bundleDir> when missing (cached afterwards), then
// renders composition ProcedureVideo with onProgress heartbeats for polling.
import { bundle } from "@remotion/bundler";
import { renderMedia, selectComposition } from "@remotion/renderer";
import fs from "node:fs";
import path from "node:path";
import { serveAssets, rewritePropsForRender } from "./asset-server.mjs";

function arg(name) {
  const i = process.argv.indexOf(name);
  return i === -1 ? null : process.argv[i + 1];
}

const bundleDir = path.resolve(arg("--bundle"));
const projectDir = path.resolve(arg("--project"));
const propsPath = path.resolve(arg("--props"));
const outPath = path.resolve(arg("--out"));
const progressArg = arg("--progress");
const progressPath = progressArg ? path.resolve(progressArg) : null;

if (!bundleDir || !projectDir || !propsPath || !outPath) {
  console.error("usage: node render.mjs --bundle <dir> --project <dir> --props <json> --out <mp4> [--progress <json>]");
  process.exit(2);
}

function writeProgress(p) {
  if (!progressPath) return;
  try {
    fs.writeFileSync(progressPath, JSON.stringify({ progress: p }));
  } catch {
    // progress file is best-effort; the render itself matters
  }
}

const rawProps = JSON.parse(fs.readFileSync(propsPath, "utf-8"));

// Absolute disk paths are invisible to headless Chrome (it resolves them
// against the bundle origin -> 404), so serve every local asset over
// loopback HTTP and rewrite the props. Nulls and remote URLs pass through.
const assets = await serveAssets();
const inputProps = rewritePropsForRender(rawProps, (localPath, name) =>
  assets.urlFor(localPath, name)
);

let serveUrl = bundleDir;
try {
  const hasBundle =
    fs.existsSync(path.join(bundleDir, "index.html")) ||
    fs.existsSync(path.join(bundleDir, "bundle.js"));
  if (!hasBundle) {
    console.log("[render] bundling Remotion project (first run)...");
    writeProgress(0.05);
    const bundled = await bundle({
      entryPoint: path.join(projectDir, "src", "index.tsx"),
      outDir: bundleDir,
    });
    serveUrl = bundled;
  }
} catch (e) {
  console.error("[render] bundle failed:", e?.message || e);
  process.exit(3);
}

try {
  const composition = await selectComposition({
    serveUrl,
    id: "ProcedureVideo",
    inputProps,
  });
  console.log(`[render] rendering ${composition.durationInFrames} frames...`);
  await renderMedia({
    composition,
    serveUrl,
    inputProps,
    codec: "h264",
    outputLocation: outPath,
    onProgress: ({ progress }) => writeProgress(progress),
  });
  console.log(`[render] done: ${outPath}`);
} catch (e) {
  console.error("[render] failed:", e?.message || e);
  await assets.close().catch(() => undefined);
  process.exit(4);
}
await assets.close().catch(() => undefined);

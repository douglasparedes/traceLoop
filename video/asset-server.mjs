// Serves per-render assets (voiceover WAV, step illustrations) to headless
// Chrome over HTTP. Absolute disk paths are invisible to the browser page
// (it resolves them against the bundle server origin -> 404), so every
// local file handed to <Audio>/<CanvasImage> must go through here.
import http from "node:http";
import fs from "node:fs";
import path from "node:path";

const MIME = {
  ".wav": "audio/wav",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".webp": "image/webp",
  ".mp4": "video/mp4",
};

/**
 * Serve local files over an ephemeral-loopback HTTP server.
 * Returns { baseUrl, urlFor(localPath, name), close }.
 * Files are NOT copied: they are served straight from disk, read-only.
 */
export async function serveAssets() {
  const server = http.createServer((req, res) => {
    // Canvas-drawn images (<CanvasImage>) require CORS even on loopback.
    const cors = { "Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS" };
    if (req.method === "OPTIONS") {
      res.writeHead(204, cors);
      res.end();
      return;
    }
    try {
      const url = new URL(req.url || "/", "http://127.0.0.1");
      const file = fileFor(url.pathname);
      if (!file || !fs.existsSync(file)) {
        res.writeHead(404, { "content-type": "text/plain" });
        res.end("not found");
        return;
      }
      const ext = path.extname(file).toLowerCase();
      const stat = fs.statSync(file);
      res.writeHead(200, {
        ...cors,
        "content-type": MIME[ext] || "application/octet-stream",
        "content-length": stat.size,
        "accept-ranges": "bytes",
      });
      fs.createReadStream(file).pipe(res);
    } catch {
      try {
        res.writeHead(500, { "content-type": "text/plain" });
        res.end("error");
      } catch {
        /* client gone */
      }
    }
  });

  const registry = new Map();
  function fileFor(pathname) {
    const name = decodeURIComponent(pathname.replace(/^\//, ""));
    if (!name || name.includes("..") || name.includes("/") || name.includes("\\")) return null;
    return registry.get(name) || null;
  }

  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => resolve());
  });
  const address = server.address();
  const baseUrl = `http://127.0.0.1:${typeof address === "object" && address ? address.port : 0}`;

  return {
    baseUrl,
    urlFor(localPath, name) {
      registry.set(name, localPath);
      return `${baseUrl}/${encodeURIComponent(name)}`;
    },
    async close() {
      await new Promise((resolve) => server.close(() => resolve()));
    },
  };
}

/**
 * Rewrite composition props so every local file becomes an http(s) URL.
 * Absolute disk paths (and anything that is not already http/https/data:)
 * go through publish(); nulls and existing URLs pass through untouched.
 */
export function rewritePropsForRender(props, publish) {
  const out = { ...props };
  if (typeof props.voiceover === "string" && props.voiceover && !/^(https?:|data:)/.test(props.voiceover)) {
    out.voiceover = publish(props.voiceover, `voiceover${path.extname(props.voiceover) || ".wav"}`);
  }
  out.scenes = (props.scenes || []).map((s, i) => {
    if (typeof s.image === "string" && s.image && !/^(https?:|data:)/.test(s.image)) {
      return { ...s, image: publish(s.image, `step-${i}${path.extname(s.image) || ".png"}`) };
    }
    return s;
  });
  return out;
}

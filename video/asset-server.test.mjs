// Covers docs/remotion rule: every local asset handed to the renderer must
// be an http(s) URL the headless browser can fetch — never a bare disk path.
import { describe, it } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { serveAssets, rewritePropsForRender } from "./asset-server.mjs";

describe("serveAssets", () => {
  it("serves local files over loopback http with correct mime", async () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "tg-assets-"));
    const png = path.join(dir, "a.png");
    fs.writeFileSync(png, Buffer.from([137, 80, 78, 71, 13, 10, 26, 10, 0]));
    const srv = await serveAssets();
    try {
      const url = srv.urlFor(png, "a.png");
      assert.match(url, /^http:\/\/127\.0\.0\.1:\d+\/a\.png$/);
      const res = await fetch(url);
      assert.equal(res.status, 200);
      assert.equal(res.headers.get("content-type"), "image/png");
      assert.equal(res.headers.get("access-control-allow-origin"), "*");
      assert.equal((await res.arrayBuffer()).byteLength, 9);
    } finally {
      await srv.close();
    }
    fs.rmSync(dir, { recursive: true, force: true });
  });

  it("returns 404 for unknown or escaping paths", async () => {
    const srv = await serveAssets();
    try {
      const base = srv.baseUrl;
      for (const p of ["/nope.png", "/..%2fsecret", "/a/b.png"]) {
        const res = await fetch(base + p);
        assert.equal(res.status, 404);
      }
    } finally {
      await srv.close();
    }
  });
});

describe("rewritePropsForRender", () => {
  const publish = (localPath, name) => `http://127.0.0.1:9/${name}`;

  it("rewrites absolute disk paths to http URLs, keeps nulls and remotes", () => {
    const out = rewritePropsForRender(
      {
        title: "t",
        voiceover: "/data/v/voiceover.wav",
        scenes: [
          { step: 1, image: "/data/v/obj-1.png" },
          { step: 2, image: null },
          { step: 3, image: "https://cdn.example/x.png" },
        ],
      },
      publish
    );
    assert.match(out.voiceover, /^http:\/\/127\.0\.0\.1:9\/voiceover\.wav$/);
    assert.match(out.scenes[0].image, /^http:\/\/127\.0\.0\.1:9\/step-0\.png$/);
    assert.equal(out.scenes[1].image, null);
    assert.equal(out.scenes[2].image, "https://cdn.example/x.png");
  });

  it("leaves a voiceless props object untouched", () => {
    const out = rewritePropsForRender({ title: "t", voiceover: null, scenes: [] }, publish);
    assert.equal(out.voiceover, null);
    assert.deepEqual(out.scenes, []);
  });
});

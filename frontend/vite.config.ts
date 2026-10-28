import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";
import { readdirSync, readFileSync, writeFileSync } from "node:fs";
import { join, posix } from "node:path";

// Inject the hashed build assets into dist/sw.js so first-visit offline works.
// public/sw.js keeps a /*__FG_PRECACHE__*/ placeholder with a dev fallback.
function precacheSw(): Plugin {
  return {
    name: "fieldguard-precache-sw",
    apply: "build",
    closeBundle() {
      const outDir = join(__dirname, "dist");
      const files: string[] = [];
      const walk = (dir: string, base: string) => {
        for (const entry of readdirSync(dir, { withFileTypes: true })) {
          const full = join(dir, entry.name);
          const rel = base ? `${base}/${entry.name}` : entry.name;
          if (entry.isDirectory()) {
            if (entry.name === "data") continue;
            walk(full, rel);
          } else if (
            entry.name === "index.html" ||
            entry.name === "manifest.webmanifest" ||
            entry.name === "sw.js" ||
            /^icon-.*\.png$/.test(entry.name) ||
            rel.startsWith("assets/")
          ) {
            files.push(`/${rel.split("\\").join(posix.sep)}`);
          }
        }
      };
      walk(outDir, "");
      if (!files.includes("/")) files.unshift("/");
      const swPath = join(outDir, "sw.js");
      try {
        const sw = readFileSync(swPath, "utf8");
        const list = JSON.stringify([...new Set(files)].sort());
        writeFileSync(swPath, sw.replace(/\/\*__FG_PRECACHE__\*\/\[[^\]]*\]/, `/*__FG_PRECACHE__*/${list}`));
        // eslint-disable-next-line no-console
        console.log(`[precache-sw] injected ${files.length} shell assets into sw.js`);
      } catch {
        // dist/sw.js missing (e.g. public dir disabled) — nothing to patch.
      }
    },
  };
}

export default defineConfig({
  plugins: [react(), precacheSw()],
  server: { proxy: { "/api": { target: "http://localhost:8000", ws: true } } },
});

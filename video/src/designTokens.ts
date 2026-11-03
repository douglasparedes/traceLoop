// TraceLoop shared video design tokens.
//
// Single source of truth for the instructional composition. Values mirror
// frontend/src/styles.css (premium theme) so generated videos and generated
// guides read as one product: same accent, same radii, same type scale,
// same safe margins. Do not hard-code diverging literals in scenes.
export const TOKENS = {
  canvas: { w: 1280, h: 720 },
  bg: "#0b1f1a",
  panel: "#122b24",
  accent: "#ffb020", // == --seg
  accentInk: "#201600", // == --seg-ink
  text: "#f2fcf2",
  muted: "#9fc3b5",
  font: "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif",
  radius: { card: 18, pill: 14, badge: 16 },
  // Balanced instructional-video layout (16:9): ~60% text/instruction,
  // ~30% supporting illustration card, rest spacing + captions. Images
  // render contained in the fixed side card — never full-bleed.
  safe: { x: 64, top: 150, bottom: 170 },
  imageCard: { maxW: 380, maxH: 300, radius: 18 },
  caption: { maxLines: 2, font: 32, fontBig: 38, bottom: 52 },
  header: { top: 44, badge: 72 },
  overlay: { dim: "brightness(0.55)" },
} as const;

export type Tokens = typeof TOKENS;

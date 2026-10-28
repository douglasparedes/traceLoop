// Live (near-live) SAM 3.1 configuration — Option A: clip chunking.
// Meta SAM video segments whole clips, so the client captures short
// frame chunks; each chunk is assembled to MP4 server-side and tracked
// by SAM, then masks play back over the captured frames. Expect a
// 5–10s delay between capture and the first tracked chunk.
export const SAM_LIVE = {
  /** Longest side of a captured frame, in pixels. */
  MAX_WIDTH: 512,
  /** JPEG quality for captured frames (0–1). */
  JPEG_QUALITY: 0.65,
  /** Frame capture rate while live. */
  TARGET_FPS: 6,
  /** Frames per chunk sent to the server. */
  CHUNK_FRAMES: 30,
  /** Maximum tracked objects rendered. */
  MAX_OBJECTS: 3,
  /** Chunk send latency (ms) above which the HUD warns about delay. */
  SLOW_CHUNK_MS: 8000,
} as const;

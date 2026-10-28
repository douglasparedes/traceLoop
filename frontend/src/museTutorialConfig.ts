// TutorialMode configuration. All AI calls go through the backend;
// model ids here are display labels matching backend env configuration.
export const TUTORIAL = {
  MUSE_TRANSCRIBE_MODEL: "muse-voice-transcribe-1.0",
  MUSE_LLM_MODEL: "muse-spark-1.3",
  SAM_MODEL: "sam-3.1",
  MAX_VIDEO_SEC: 600,
  MAX_WIDTH: 1280,
  TRACKING_FPS: 6,
  CONF_THRESHOLD: 0.4,
  POLL_MS: 2000,
} as const;

export const STATUS_LABELS: Record<string, string> = {
  uploaded: "Uploaded — starting…",
  transcribing: "Transcribing with Muse Voice…",
  understanding: "Understanding steps & objects with Muse Spark…",
  segmenting: "Segmenting objects with SAM 3.1…",
  illustrating: "Building illustrations…",
  generating: "Writing your guide with Muse Spark…",
  done: "Guide ready",
  error: "Something went wrong",
};

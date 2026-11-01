// TraceLoop procedure video guide — Remotion composition.
//
// Written against docs/remotion/markup-SKILL.md:
// - interpolate() + useCurrentFrame() only (no CSS transitions/animations)
// - fps from useVideoConfig() for every seconds<->frames conversion
// - deterministic: no Math.random/Date.now — same props, same pixels
// - duration/dimensions from calculateMetadata (see ./index.ts)
import React from "react";
import {
  AbsoluteFill,
  Audio,
  CanvasImage,
  Easing,
  interpolate,
  Sequence,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { z } from "zod";

export const SceneSchema = z.object({
  step: z.number(),
  title: z.string(),
  caption: z.string(),
  image: z.string().nullable(),
  startFrame: z.number(),
  durationFrames: z.number(),
});

export const VideoPropsSchema = z.object({
  title: z.string(),
  fps: z.number(),
  width: z.number(),
  height: z.number(),
  voiceover: z.string().nullable(),
  voiceoverFrames: z.number(),
  scenes: z.array(SceneSchema),
  totalFrames: z.number(),
});

export type VideoProps = z.infer<typeof VideoPropsSchema>;

const BRAND_BG = "#0b1f1a";
const BRAND_PANEL = "#122b24";
const BRAND_ACCENT = "#ffb020";
const BRAND_TEXT = "#f2fcf2";
const BRAND_MUTED = "#9fc3b5";
const FONT = "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif";

function useFadeIn(frames = 15): number {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const span = Math.max(1, Math.round((frames / 30) * fps));
  return interpolate(frame, [0, span], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.bezier(0.16, 1, 0.3, 1),
  });
}

const TitleCard: React.FC<{ title: string }> = ({ title }) => {
  const opacity = useFadeIn();
  const frame = useCurrentFrame();
  const scale = interpolate(frame, [0, 30], [0.96, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.bezier(0.16, 1, 0.3, 1),
  });
  return (
    <AbsoluteFill
      style={{
        backgroundColor: BRAND_BG,
        justifyContent: "center",
        alignItems: "center",
        opacity,
        scale,
        fontFamily: FONT,
      }}
    >
      <div style={{ fontSize: 28, color: BRAND_ACCENT, letterSpacing: 4 }}>TRACELOOP GUIDE</div>
      <div style={{ fontSize: 64, color: BRAND_TEXT, fontWeight: 700, textAlign: "center", padding: "0 120px", marginTop: 16 }}>
        {title}
      </div>
    </AbsoluteFill>
  );
};

const StepScene: React.FC<{ scene: z.infer<typeof SceneSchema>; total: number }> = ({ scene, total }) => {
  const opacity = useFadeIn();
  const frame = useCurrentFrame();
  const slide = interpolate(frame, [0, 20], [40, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.bezier(0.16, 1, 0.3, 1),
  });
  return (
    <AbsoluteFill style={{ backgroundColor: BRAND_BG, opacity, fontFamily: FONT }}>
      <div
        style={{
          position: "absolute",
          top: 48,
          left: 64,
          right: 64,
          display: "flex",
          alignItems: "center",
          gap: 24,
          translate: `0px ${slide}px`,
        }}
      >
        <div
          style={{
            width: 72,
            height: 72,
            borderRadius: 16,
            backgroundColor: BRAND_ACCENT,
            color: "#201600",
            fontSize: 40,
            fontWeight: 800,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          {scene.step}
        </div>
        <div>
          <div style={{ fontSize: 44, color: BRAND_TEXT, fontWeight: 700 }}>{scene.title}</div>
          <div style={{ fontSize: 22, color: BRAND_MUTED }}>
            Step {scene.step} of {total}
          </div>
        </div>
      </div>
      {scene.image ? (
        <CanvasImage
          src={scene.image}
          style={{
            position: "absolute",
            top: 200,
            left: 64,
            width: 1152,
            height: 380,
            objectFit: "contain",
            backgroundColor: BRAND_PANEL,
            borderRadius: 16,
          }}
        />
      ) : (
        <div
          style={{
            position: "absolute",
            top: 200,
            left: 64,
            width: 1152,
            height: 380,
            backgroundColor: BRAND_PANEL,
            borderRadius: 16,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            color: BRAND_MUTED,
            fontSize: 30,
          }}
        >
          No illustration for this step — follow the narration
        </div>
      )}
      <div
        style={{
          position: "absolute",
          bottom: 56,
          left: 64,
          right: 64,
          backgroundColor: "rgba(0,0,0,0.72)",
          borderRadius: 14,
          padding: "18px 26px",
          fontSize: 32,
          color: BRAND_TEXT,
          textAlign: "center",
        }}
      >
        {scene.caption}
      </div>
    </AbsoluteFill>
  );
};

export const ProcedureVideo: React.FC<VideoProps> = (props) => {
  const titleFrames = Math.round(1.5 * props.fps);
  return (
    <AbsoluteFill style={{ backgroundColor: BRAND_BG }}>
      <Sequence durationInFrames={titleFrames}>
        <TitleCard title={props.title} />
      </Sequence>
      {props.scenes.map((s) => (
        <Sequence key={s.step} from={s.startFrame} durationInFrames={s.durationFrames}>
          <StepScene scene={s} total={props.scenes.length} />
        </Sequence>
      ))}
      {props.voiceover ? <Audio src={props.voiceover} volume={1} /> : null}
    </AbsoluteFill>
  );
};

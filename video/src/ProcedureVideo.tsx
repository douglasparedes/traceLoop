// TraceLoop procedure video guide — Remotion composition.
//
// Written against docs/remotion/markup-SKILL.md:
// - interpolate()/spring() + useCurrentFrame() only (no CSS transitions/
//   animations, no randomness, no Date.now — same props, same pixels)
// - fps from useVideoConfig() for every seconds<->frames conversion
// - duration/dimensions from calculateMetadata (see ./index.ts)
// - Zod schema validates server-generated props at the render boundary;
//   beats/tools/expected are optional so older saved props keep rendering.
import React from "react";
import {
  AbsoluteFill,
  Audio,
  CanvasImage,
  Easing,
  Img,
  interpolate,
  Sequence,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { z } from "zod";

export const BeatSchema = z.object({
  kind: z.enum(["hero", "detail", "caption", "verify"]),
  image: z.string().nullable(),
  headline: z.string(),
  body: z.string(),
  startFrame: z.number(),
  durationFrames: z.number(),
});

export const SceneSchema = z.object({
  step: z.number(),
  title: z.string(),
  caption: z.string(),
  image: z.string().nullable(),
  startFrame: z.number(),
  durationFrames: z.number(),
  expected: z.string().optional(),
  tools: z.array(z.string()).optional(),
  imageW: z.number().optional(),
  imageH: z.number().optional(),
  beats: z.array(BeatSchema).optional(),
});

export const VideoPropsSchema = z.object({
  title: z.string(),
  fps: z.number(),
  width: z.number(),
  height: z.number(),
  format: z.string().optional(),
  voiceover: z.string().nullable(),
  voiceoverFrames: z.number(),
  scenes: z.array(SceneSchema),
  totalFrames: z.number(),
});

export type VideoProps = z.infer<typeof VideoPropsSchema>;
type Scene = z.infer<typeof SceneSchema>;
type Beat = z.infer<typeof BeatSchema>;

const BRAND_BG = "#0b1f1a";
const BRAND_PANEL = "#122b24";
const BRAND_ACCENT = "#ffb020";
const BRAND_TEXT = "#f2fcf2";
const BRAND_MUTED = "#9fc3b5";
const FONT = "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif";

const FORMAT_EYEBROW: Record<string, string> = {
  work_instruction: "TRACELOOP GUIDE",
  reference_manual: "REFERENCE",
  interactive: "GUIDED EXECUTION",
};

function stepWord(format?: string): string {
  if (format === "reference_manual") return "Section";
  if (format === "interactive") return "Action";
  return "Step";
}

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

const TitleCard: React.FC<{ title: string; format?: string }> = ({ title, format }) => {
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
      <div style={{ fontSize: 28, color: BRAND_ACCENT, letterSpacing: 4 }}>{FORMAT_EYEBROW[format || ""] || "TRACELOOP GUIDE"}</div>
      <div style={{ fontSize: 64, color: BRAND_TEXT, fontWeight: 700, textAlign: "center", padding: "0 120px", marginTop: 16 }}>
        {title}
      </div>
    </AbsoluteFill>
  );
};

/** 16:9-aware image treatment. Portrait sources get a blurred full-frame
 *  backdrop plus a contained main visual — the frame is always filled,
 *  important content is never cropped away. */
const StepImage: React.FC<{ src: string | null; portrait: boolean; zoomFrom: number; zoomTo: number; dim?: boolean; mainW?: number; mainH?: number }> = ({
  src, portrait, zoomFrom, zoomTo, dim, mainW, mainH,
}) => {
  const frame = useCurrentFrame();
  const zoom = interpolate(frame, [0, Math.max(1, 60)], [zoomFrom, zoomTo], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.bezier(0.16, 1, 0.3, 1),
  });
  if (!src) {
    return (
      <AbsoluteFill style={{ backgroundColor: BRAND_PANEL, justifyContent: "center", alignItems: "center" }}>
        <div style={{ color: BRAND_MUTED, fontSize: 28, fontFamily: FONT }}>
          Visual unavailable — see render diagnostics
        </div>
      </AbsoluteFill>
    );
  }
  if (!portrait) {
    return (
      <AbsoluteFill>
        <CanvasImage
          src={src}
          style={{
            width: "100%",
            height: "100%",
            objectFit: "cover",
            scale: zoom,
            filter: dim ? "brightness(0.55)" : undefined,
          }}
        />
      </AbsoluteFill>
    );
  }
  // Explicit pixel geometry + absolute centering: flex centering of
  // canvas-backed visuals is unreliable in headless SSR renders.
  const h = mainH || 446;
  const w = mainW || 300;
  const cx = Math.round((1280 - w) / 2);
  const cy = Math.round(Math.min(Math.max(380 - h / 2, 165), 720 - 140 - h));
  return (
    <AbsoluteFill style={{ backgroundColor: BRAND_BG, justifyContent: "center", alignItems: "center" }}>
      <CanvasImage
        src={src}
        style={{
          position: "absolute",
          width: "100%",
          height: "100%",
          objectFit: "cover",
          filter: "blur(28px) brightness(0.45)",
          scale: 1.15,
        }}
      />
      <Img
        src={src}
        style={{
          position: "absolute",
          left: cx,
          top: cy,
          width: w,
          height: h,
          objectFit: "contain",
          borderRadius: 18,
          scale: zoom,
          filter: dim ? "brightness(0.7)" : undefined,
        }}
      />
    </AbsoluteFill>
  );
};

const StepHeader: React.FC<{ scene: Scene; total: number; format?: string }> = ({ scene, total, format }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const pop = spring({ frame, fps, config: { damping: 200, stiffness: 260 } });
  const badgeScale = interpolate(pop, [0, 1], [0.7, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return (
    <div
      style={{
        position: "absolute",
        top: 44,
        left: 64,
        right: 64,
        display: "flex",
        alignItems: "center",
        gap: 24,
        fontFamily: FONT,
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
          scale: badgeScale,
        }}
      >
        {scene.step}
      </div>
      <div>
        <div style={{ fontSize: 44, color: BRAND_TEXT, fontWeight: 700 }}>{scene.title}</div>
        <div style={{ fontSize: 22, color: BRAND_MUTED }}>
          {stepWord(format)} {scene.step} of {total}
        </div>
      </div>
    </div>
  );
};

const ProgressRail: React.FC<{ index: number; total: number }> = ({ index, total }) => {
  const frame = useCurrentFrame();
  const width = interpolate(frame, [0, 20], [0, 100], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return (
    <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: 8, backgroundColor: "rgba(255,255,255,0.12)" }}>
      <div style={{ width: `${((index + width / 100) / Math.max(1, total)) * 100}%`, height: "100%", backgroundColor: BRAND_ACCENT }} />
    </div>
  );
};

const CaptionBar: React.FC<{ text: string; big?: boolean }> = ({ text, big }) => {
  const opacity = useFadeIn(10);
  return (
    <div
      style={{
        position: "absolute",
        bottom: 52,
        left: 64,
        right: 64,
        backgroundColor: "rgba(0,0,0,0.72)",
        borderRadius: 14,
        padding: "18px 26px",
        fontSize: big ? 38 : 32,
        color: BRAND_TEXT,
        textAlign: "center",
        opacity,
        fontFamily: FONT,
      }}
    >
      {text}
    </div>
  );
};

/** One visual beat: dissolves in over the outgoing beat and holds a
 *  purposeful camera move or overlay for its whole duration — never a
 *  frozen still, never a dip to black. */
const BeatView: React.FC<{ scene: Scene; beat: Beat; beatIndex: number }> = ({ scene, beat, beatIndex }) => {
  const frame = useCurrentFrame();
  const tools = scene.tools || [];
  const fadeLen = 8;
  // Dissolve in over the outgoing beat (which stays fully opaque beneath).
  const fadeIn = interpolate(frame, [0, fadeLen], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const portrait = (scene.imageH || 0) > (scene.imageW || 0);
  return (
    <AbsoluteFill style={{ opacity: fadeIn, backgroundColor: BRAND_BG }}>
      {beat.kind === "verify" ? (
        <AbsoluteFill style={{ backgroundColor: BRAND_BG, justifyContent: "center", alignItems: "center", fontFamily: FONT }}>
          <div style={{ backgroundColor: BRAND_PANEL, borderRadius: 20, padding: "48px 72px", maxWidth: 980, border: `2px solid ${BRAND_ACCENT}` }}>
            <div style={{ fontSize: 26, color: BRAND_ACCENT, letterSpacing: 3 }}>EXPECTED RESULT</div>
            <div style={{ fontSize: 40, color: BRAND_TEXT, fontWeight: 700, marginTop: 16 }}>
              {beat.body || scene.expected || scene.caption}
            </div>
            {(tools).length > 0 && (
              <div style={{ fontSize: 26, color: BRAND_MUTED, marginTop: 20 }}>
                Tools: {tools.join(" · ")}
              </div>
            )}
          </div>
        </AbsoluteFill>
      ) : (
        <>
          <StepImage
            src={beat.image}
            portrait={portrait}
            zoomFrom={beat.kind === "hero" ? 1 : 1.02}
            zoomTo={beat.kind === "hero" ? 1.08 : 1.16}
            dim={beat.kind === "caption"}
            mainW={Math.min(900, Math.round(446 * (scene.imageW || 3) / Math.max(1, scene.imageH || 4)))}
            mainH={446}
          />
          {beat.kind === "caption" ? (
            <AbsoluteFill style={{ justifyContent: "center", alignItems: "center", padding: "0 120px" }}>
              <div style={{ fontSize: 44, color: BRAND_TEXT, fontWeight: 700, textAlign: "center", fontFamily: FONT, opacity: useFadeIn(10) }}>
                {beat.body}
              </div>
            </AbsoluteFill>
          ) : (
            <>
              {beatIndex > 0 || beat.kind === "detail" ? (
                <div style={{
                  position: "absolute", top: 150, left: 64,
                  backgroundColor: "rgba(0,0,0,0.68)", borderRadius: 10, padding: "10px 20px",
                  fontSize: 26, color: BRAND_ACCENT, letterSpacing: 2, fontFamily: FONT, opacity: fadeIn,
                }}>
                  {beat.kind === "detail" ? "FOCUS" : beat.headline || "STEP"}
                </div>
              ) : null}
              <CaptionBar text={beat.body || scene.caption} />
            </>
          )}
        </>
      )}
    </AbsoluteFill>
  );
};

const StepScene: React.FC<{ scene: Scene; total: number; format?: string }> = ({ scene, total, format }) => {
  const beats = (scene.beats || []).filter((b) => b.durationFrames > 0);
  if (!beats.length) {
    // Backward compatible: older saved props without beats render as before.
    const portrait = (scene.imageH || 0) > (scene.imageW || 0);
    return (
      <AbsoluteFill style={{ backgroundColor: BRAND_BG, fontFamily: FONT }}>
        <StepImage src={scene.image} portrait={portrait} zoomFrom={1} zoomTo={1.06}
          mainW={Math.min(900, Math.round(446 * (scene.imageW || 3) / Math.max(1, scene.imageH || 4)))}
          mainH={446} />
        <StepHeader scene={scene} total={total} format={format} />
        <CaptionBar text={scene.caption} />
      </AbsoluteFill>
    );
  }
  const index = Math.max(0, scene.step - 1);
  return (
    <AbsoluteFill style={{ backgroundColor: BRAND_BG, fontFamily: FONT }}>
      {beats.map((b, i) => (
        // Overlap into the next beat's fade window so the outgoing visual
        // stays mounted beneath the incoming dissolve (except the last).
        <Sequence key={i} from={b.startFrame - scene.startFrame}
          durationInFrames={b.durationFrames + (i < beats.length - 1 ? 8 : 0)}>
          <BeatView scene={scene} beat={b} beatIndex={i} />
        </Sequence>
      ))}
      <StepHeader scene={scene} total={total} format={format} />
      <ProgressRail index={index} total={total} />
    </AbsoluteFill>
  );
};

export const ProcedureVideo: React.FC<VideoProps> = (props) => {
  const titleFrames = Math.round(1.5 * props.fps);
  return (
    <AbsoluteFill style={{ backgroundColor: BRAND_BG }}>
      <Sequence durationInFrames={titleFrames}>
        <TitleCard title={props.title} format={props.format} />
      </Sequence>
      {props.scenes.map((s) => (
        <Sequence key={s.step} from={s.startFrame} durationInFrames={s.durationFrames}>
          <StepScene scene={s} total={props.scenes.length} format={props.format} />
        </Sequence>
      ))}
      {props.voiceover ? (
        <Sequence from={titleFrames} durationInFrames={Math.max(1, props.totalFrames - titleFrames)}>
          <Audio src={props.voiceover} volume={1} />
        </Sequence>
      ) : null}
    </AbsoluteFill>
  );
};

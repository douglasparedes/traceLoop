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
  instruction: z.string().optional(),
  narration: z.string().optional(),
  caption_chunks: z.array(z.string()).optional(),
  objects_used: z.array(z.number()).optional(),
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

import { TOKENS } from "./designTokens";

const BRAND_BG = TOKENS.bg;
const BRAND_PANEL = TOKENS.panel;
const BRAND_ACCENT = TOKENS.accent;
const BRAND_TEXT = TOKENS.text;
const BRAND_MUTED = TOKENS.muted;
const FONT = TOKENS.font;

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

/** Instruction-first side layout (16:9): text panel carries the guide
 *  step (~60-65% of the canvas), supporting image is a compact side card
 *  (~30%), captions own the bottom safe area. Illustrations support the
 *  instruction — never the reverse. */
const LAYOUT = {
  headerTop: 44,
  contentTop: 150,
  captionTop: 550,
  textX: 64,
  textW: 660,
  gap: 40,
  imgX: 764,
  imgW: 380,
  imgH: 300,
  radius: 18,
} as const;

/** Compact supporting visual: contained card, aspect preserved, aligned
 *  highlight geometry. Portrait and landscape both fit — never cropped. */
const StepImage: React.FC<{ src: string | null; portrait: boolean; zoomFrom: number; zoomTo: number; dim?: boolean; label?: string }> = ({
  src, portrait, zoomFrom, zoomTo, dim, label,
}) => {
  const frame = useCurrentFrame();
  const zoom = interpolate(frame, [0, Math.max(1, 60)], [zoomFrom, zoomTo], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.bezier(0.16, 1, 0.3, 1),
  });
  if (!src) {
    return (
      <div style={{
        position: "absolute", left: LAYOUT.imgX, top: LAYOUT.contentTop,
        width: LAYOUT.imgW, height: LAYOUT.imgH, borderRadius: LAYOUT.radius,
        backgroundColor: BRAND_PANEL, display: "flex",
        alignItems: "center", justifyContent: "center",
        color: BRAND_MUTED, fontSize: 22, fontFamily: FONT, textAlign: "center",
        padding: 20,
      }}>
        Visual unavailable — see render diagnostics
      </div>
    );
  }
  void portrait;
  return (
    <div style={{ position: "absolute", left: LAYOUT.imgX, top: LAYOUT.contentTop }}>
      <Img
        src={src}
        style={{
          width: LAYOUT.imgW,
          height: LAYOUT.imgH,
          objectFit: "contain",
          borderRadius: LAYOUT.radius,
          scale: zoom,
          filter: dim ? TOKENS.overlay.dim : undefined,
          backgroundColor: BRAND_PANEL,
        }}
      />
      {label ? (
        <div style={{
          position: "absolute", left: 12, bottom: 12,
          backgroundColor: "rgba(0,0,0,0.72)", borderRadius: 8, padding: "6px 12px",
          fontSize: 20, color: BRAND_ACCENT, letterSpacing: 1, fontFamily: FONT,
        }}>
          {label}
        </div>
      ) : null}
    </div>
  );
};

const InstructionPanel: React.FC<{ scene: Scene; total: number; format?: string }> = ({ scene, total, format }) => {
  const instruction = (scene.instruction || "").trim();
  const tools = scene.tools || [];
  return (
    <div style={{
      position: "absolute", left: LAYOUT.textX, top: LAYOUT.contentTop,
      width: LAYOUT.textW, fontFamily: FONT,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
        <div style={{
          width: 56, height: 56, borderRadius: 14, backgroundColor: BRAND_ACCENT,
          color: "#201600", fontSize: 30, fontWeight: 800,
          display: "flex", alignItems: "center", justifyContent: "center",
        }}>
          {scene.step}
        </div>
        <div>
          <div style={{ fontSize: 34, color: BRAND_TEXT, fontWeight: 700, lineHeight: 1.15 }}>{scene.title}</div>
          <div style={{ fontSize: 20, color: BRAND_MUTED, marginTop: 2 }}>
            {stepWord(format)} {scene.step} of {total}
          </div>
        </div>
      </div>
      {instruction ? (
        <div style={{ fontSize: 26, color: BRAND_TEXT, marginTop: 18, lineHeight: 1.35 }}>{instruction}</div>
      ) : null}
      {scene.expected ? (
        <div style={{ fontSize: 22, color: BRAND_MUTED, marginTop: 14 }}>
          <span style={{ color: BRAND_ACCENT, letterSpacing: 2, fontSize: 18 }}>EXPECTED RESULT · </span>
          {scene.expected}
        </div>
      ) : null}
      {tools.length > 0 ? (
        <div style={{ fontSize: 20, color: BRAND_MUTED, marginTop: 10 }}>
          Tools: {tools.join(" · ")}
        </div>
      ) : null}
    </div>
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

/** One visual beat: same static instruction panel throughout; exactly one
 *  caption chunk on screen at a time. Beats dissolve into each other —
 *  never a frozen still, never a dip to black. */
const BeatView: React.FC<{ scene: Scene; beat: Beat; beatIndex: number; total: number; format?: string }> = ({ scene, beat, beatIndex, total, format }) => {
  const frame = useCurrentFrame();
  const fadeLen = 8;
  // Dissolve in over the outgoing beat (which stays fully opaque beneath).
  const fadeIn = interpolate(frame, [0, fadeLen], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const portrait = (scene.imageH || 0) > (scene.imageW || 0);
  return (
    <AbsoluteFill style={{ opacity: fadeIn, backgroundColor: BRAND_BG }}>
      {beat.kind === "verify" ? (
        <AbsoluteFill style={{ backgroundColor: BRAND_BG, justifyContent: "center", alignItems: "center", fontFamily: FONT }}>
          <div style={{ backgroundColor: BRAND_PANEL, borderRadius: 20, padding: "40px 64px", maxWidth: 980, border: `2px solid ${BRAND_ACCENT}` }}>
            <div style={{ fontSize: 26, color: BRAND_ACCENT, letterSpacing: 3 }}>EXPECTED RESULT</div>
            <div style={{ fontSize: 36, color: BRAND_TEXT, fontWeight: 700, marginTop: 14 }}>
              {beat.body || scene.expected || scene.caption}
            </div>
            {(scene.tools || []).length > 0 && (
              <div style={{ fontSize: 24, color: BRAND_MUTED, marginTop: 18 }}>
                Tools: {(scene.tools || []).join(" · ")}
              </div>
            )}
          </div>
        </AbsoluteFill>
      ) : (
        <>
          <InstructionPanel scene={scene} total={total} format={format} />
          <StepImage
            src={beat.image}
            portrait={portrait}
            zoomFrom={beat.kind === "hero" ? 1 : 1.02}
            zoomTo={beat.kind === "hero" ? 1.06 : 1.1}
            dim={false}
            label={beat.headline || undefined}
          />
          <CaptionBar text={beat.body} />
        </>
      )}
    </AbsoluteFill>
  );
};

const StepScene: React.FC<{ scene: Scene; total: number; format?: string }> = ({ scene, total, format }) => {
  const beats = (scene.beats || []).filter((b) => b.durationFrames > 0);
  if (!beats.length) {
    // Backward compatible: older saved props without beats render the same
    // instruction-first layout with a single caption.
    const portrait = (scene.imageH || 0) > (scene.imageW || 0);
    return (
      <AbsoluteFill style={{ backgroundColor: BRAND_BG, fontFamily: FONT }}>
        <InstructionPanel scene={scene} total={total} format={format} />
        <StepImage src={scene.image} portrait={portrait} zoomFrom={1} zoomTo={1.05} />
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
          <BeatView scene={scene} beat={b} beatIndex={i} total={total} format={format} />
        </Sequence>
      ))}
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

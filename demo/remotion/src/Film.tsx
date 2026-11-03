import React from "react";
import { AbsoluteFill, Audio, OffthreadVideo, Sequence, staticFile, useCurrentFrame, interpolate } from "remotion";
import { z } from "zod";

export const FilmPropsSchema = z.object({
  voiceoverSrc: z.string().nullable().optional(),
});
export type FilmProps = z.infer<typeof FilmPropsSchema>;

const FONT = "Arial, 'Segoe UI', sans-serif";
const BG = "#0B1F1A";
const ACCENT = "#FFB020";

const Chyron: React.FC<{ index: string; title: string; sub: string }> = ({ index, title, sub }) => {
  const f = useCurrentFrame();
  const o =
    interpolate(f, [0, 8], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }) *
    (1 - interpolate(f, [52, 64], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }));
  return (
    <div style={{ position: "absolute", left: 72, bottom: 54, opacity: o, fontFamily: FONT, display: "flex", alignItems: "center", gap: 18 }}>
      <div style={{ background: ACCENT, color: "#201600", fontWeight: 800, fontSize: 26, borderRadius: 10, padding: "10px 18px" }}>{index}</div>
      <div>
        <div style={{ color: "#F2FCF2", fontWeight: 800, fontSize: 34 }}>{title}</div>
        <div style={{ color: "#9FC3B5", fontSize: 24 }}>{sub}</div>
      </div>
    </div>
  );
};

const Zoom: React.FC<{ children: React.ReactNode; len: number }> = ({ children, len }) => {
  const f = useCurrentFrame();
  const z = interpolate(f, [0, len], [1, 1.045], { extrapolateRight: "clamp" });
  return <div style={{ width: "100%", height: "100%", transform: `scale(${z})` }}>{children}</div>;
};

const Clip: React.FC<{ src: string; len: number; label: [string, string, string] }> = ({ src, len, label }) => (
  <AbsoluteFill style={{ backgroundColor: BG }}>
    <Zoom len={len}>
      <OffthreadVideo src={staticFile(src)} style={{ width: "100%", height: "100%", objectFit: "cover" }} pauseWhenBuffering />
    </Zoom>
    <Chyron index={label[0]} title={label[1]} sub={label[2]} />
  </AbsoluteFill>
);

const MobileClip: React.FC<{ src: string; len: number; label: [string, string, string] }> = ({ src, len, label }) => (
  <AbsoluteFill style={{ backgroundColor: BG, flexDirection: "row", display: "flex", alignItems: "center", justifyContent: "center" }}>
    <div style={{ width: 500, height: 1080, borderLeft: "1px solid rgba(255,255,255,0.14)", borderRight: "1px solid rgba(255,255,255,0.14)" }}>
      <OffthreadVideo src={staticFile(src)} style={{ width: "100%", height: "100%", objectFit: "fill" }} pauseWhenBuffering />
    </div>
    <div style={{ position: "absolute", left: 120, top: 120, fontFamily: FONT }}>
      <div style={{ color: ACCENT, fontSize: 30, letterSpacing: 5, fontWeight: 800 }}>{label[0]} · FIELD CAPTURE</div>
      <div style={{ color: "#F2FCF2", fontSize: 44, fontWeight: 800, marginTop: 10 }}>{label[1]}</div>
      <div style={{ color: "#9FC3B5", fontSize: 27, marginTop: 8 }}>{label[2]}</div>
    </div>
    <div style={{ position: "absolute", right: 120, top: 120, fontFamily: FONT, textAlign: "right" }}>
      <div style={{ color: "#9FC3B5", fontSize: 26 }}>real phone viewport</div>
      <div style={{ color: "#F2FCF2", fontSize: 40, fontWeight: 800 }}>390 × 844</div>
      <div style={{ color: "#9FC3B5", fontSize: 26 }}>uncropped · legible</div>
    </div>
  </AbsoluteFill>
);

const Card: React.FC<{ eyebrow: string; title: string; sub: string }> = ({ eyebrow, title, sub }) => {
  return (
    <AbsoluteFill style={{ backgroundColor: BG, justifyContent: "center", alignItems: "center", fontFamily: FONT }}>
      <div style={{ textAlign: "center" }}>
        <div style={{ color: ACCENT, fontSize: 30, letterSpacing: 8, fontWeight: 800 }}>{eyebrow}</div>
        <div style={{ color: "#F2FCF2", fontSize: 88, fontWeight: 800, marginTop: 24 }}>{title}</div>
        <div style={{ color: "#9FC3B5", fontSize: 34, marginTop: 20 }}>{sub}</div>
      </div>
    </AbsoluteFill>
  );
};

/** 9 scenes, 5400 frames. voiceoverSrc=null mounts no Audio (owner records later). */
export const HackathonFilm: React.FC<FilmProps> = ({ voiceoverSrc }) => (
  <AbsoluteFill>
    <Sequence from={0} durationInFrames={300}><Card eyebrow="TRACELOOP" title="Knowledge that never gets lost." sub="A real product demo · genuine browser footage · no narration yet" /></Sequence>
    <Sequence from={300} durationInFrames={750}><Clip src="clips/s2.mp4" len={750} label={["02", "Capture", "real upload flow"]} /></Sequence>
    <Sequence from={1050} durationInFrames={690}><Clip src="clips/s3.mp4" len={690} label={["03", "Understanding", "provenance per stage"]} /></Sequence>
    <Sequence from={1740} durationInFrames={720}><Clip src="clips/s4.mp4" len={720} label={["04", "Correction", "steps rewritten and saved"]} /></Sequence>
    <Sequence from={2460} durationInFrames={600}><Clip src="clips/s5.mp4" len={600} label={["05", "Guide", "work instruction versioned"]} /></Sequence>
    <Sequence from={3060} durationInFrames={600}><Clip src="clips/s6.mp4" len={600} label={["06", "Approval", "reviewed and approved"]} /></Sequence>
    <Sequence from={3660} durationInFrames={900}><MobileClip src="clips/s7.mp4" len={900} label={["07", "Offline execution", "saved, offline, synced"]} /></Sequence>
    <Sequence from={4560} durationInFrames={210}>
      <AbsoluteFill style={{ backgroundColor: BG }}>
        <Zoom len={210}><OffthreadVideo src={staticFile("clips/s8a.mp4")} style={{ width: "100%", height: "100%", objectFit: "cover" }} /></Zoom>
        <Chyron index="08a" title="Field feedback" sub="step marked confusing · queued note" />
      </AbsoluteFill>
    </Sequence>
    <Sequence from={4770} durationInFrames={180}>
      <AbsoluteFill style={{ backgroundColor: BG }}>
        <Zoom len={180}><OffthreadVideo src={staticFile("clips/s8b.mp4")} style={{ width: "100%", height: "100%", objectFit: "cover" }} /></Zoom>
        <Chyron index="08b" title="Improvement proposal" sub="before / after · simulated · low confidence" />
      </AbsoluteFill>
    </Sequence>
    <Sequence from={4950} durationInFrames={200}>
      <AbsoluteFill style={{ backgroundColor: BG }}>
        <Zoom len={200}><OffthreadVideo src={staticFile("clips/s8c.mp4")} style={{ width: "100%", height: "100%", objectFit: "cover" }} /></Zoom>
        <Chyron index="08c" title="Approve the fix" sub="v5 approved · job stays pinned to v3" />
      </AbsoluteFill>
    </Sequence>
    <Sequence from={5150} durationInFrames={250}><Card eyebrow="TRACELOOP" title="Capture → improve → endure." sub="github.com/douglasparedes/traceLoop · Built with Meta AI" /></Sequence>
    {voiceoverSrc ? (
      <Sequence from={0} durationInFrames={5400}><Audio src={voiceoverSrc} /></Sequence>
    ) : null}
  </AbsoluteFill>
);

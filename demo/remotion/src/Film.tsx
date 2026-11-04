import React from "react";
import { AbsoluteFill, Audio, Img, OffthreadVideo, Sequence, interpolate, staticFile, useCurrentFrame } from "remotion";
import { z } from "zod";

export const FilmPropsSchema = z.object({
  voiceoverSrc: z.string().nullable().optional(),
  musicOn: z.boolean().optional(),
});
export type FilmProps = z.infer<typeof FilmPropsSchema>;

const FONT = "Arial, 'Segoe UI', sans-serif";
const BG = "#0B1F1A";
const ACCENT = "#FFB020";
const TXT = "#F2FCF2";
const MUT = "#9FC3B5";

const Chyron: React.FC<{ index: string; title: string; sub: string }> = ({ index, title, sub }) => {
  const f = useCurrentFrame();
  const o =
    interpolate(f, [0, 8], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }) *
    (1 - interpolate(f, [52, 64], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }));
  return (
    <div style={{ position: "absolute", left: 72, bottom: 54, opacity: o, fontFamily: FONT, display: "flex", alignItems: "center", gap: 18 }}>
      <div style={{ background: ACCENT, color: "#201600", fontWeight: 800, fontSize: 26, borderRadius: 10, padding: "10px 18px" }}>{index}</div>
      <div>
        <div style={{ color: TXT, fontWeight: 800, fontSize: 34 }}>{title}</div>
        <div style={{ color: MUT, fontSize: 24 }}>{sub}</div>
      </div>
    </div>
  );
};

const Push: React.FC<{ children: React.ReactNode; len: number; to?: number }> = ({ children, len, to }) => {
  const f = useCurrentFrame();
  const z = interpolate(f, [0, len], [1, to ?? 1.045], { extrapolateRight: "clamp" });
  return <div style={{ width: "100%", height: "100%", transform: `scale(${z})` }}>{children}</div>;
};

const Full: React.FC<{ src: string; len: number; label: [string, string, string] }> = ({ src, len, label }) => (
  <AbsoluteFill style={{ backgroundColor: BG }}>
    <Push len={len}>
      <OffthreadVideo src={staticFile(src)} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
    </Push>
    <Chyron index={label[0]} title={label[1]} sub={label[2]} />
  </AbsoluteFill>
);

const Hook: React.FC = () => {
  const f = useCurrentFrame();
  const z = interpolate(f, [0, 360], [1, 1.1], { extrapolateRight: "clamp" });
  return (
    <AbsoluteFill style={{ backgroundColor: BG, alignItems: "center", justifyContent: "center", fontFamily: FONT }}>
      <div style={{ width: 609, height: 1080, overflow: "hidden", transform: `scale(${z})` }}>
        <OffthreadVideo src={staticFile("clips/g1.mp4")} style={{ width: "100%", height: "100%", objectFit: "fill" }} />
      </div>
      <div style={{ position: "absolute", left: 110, bottom: 110 }}>
        <div style={{ color: ACCENT, fontSize: 28, letterSpacing: 6, fontWeight: 800 }}>A REAL TASK, RECORDED</div>
        <div style={{ color: TXT, fontSize: 72, fontWeight: 800, marginTop: 12 }}>Expert knowledge should not disappear.</div>
      </div>
    </AbsoluteFill>
  );
};

const Field: React.FC = () => {
  const f = useCurrentFrame();
  const drain = interpolate(f, [240, 690], [1, 0.04], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const refill = interpolate(f, [690, 780], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const w = drain * (1 - refill) + refill;
  return (
    <AbsoluteFill style={{ backgroundColor: BG, display: "flex", flexDirection: "row", alignItems: "center", justifyContent: "center" }}>
      <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: 6, background: "rgba(255,255,255,0.08)" }}>
        <div style={{ width: `${w * 100}%`, height: "100%", background: refill > 0.5 ? "#7BD88F" : ACCENT }} />
      </div>
      <div style={{ width: 500, height: 1080, borderLeft: "1px solid rgba(255,255,255,0.14)", borderRight: "1px solid rgba(255,255,255,0.14)" }}>
        <OffthreadVideo src={staticFile("clips/g7m.mp4")} style={{ width: "100%", height: "100%", objectFit: "fill" }} />
      </div>
      <div style={{ position: "absolute", left: 90, top: 130, fontFamily: FONT }}>
        <div style={{ color: ACCENT, fontSize: 28, letterSpacing: 5, fontWeight: 800 }}>07 FIELD EXECUTION</div>
        <div style={{ color: TXT, fontSize: 42, fontWeight: 800, marginTop: 10 }}>Works without signal.</div>
        <div style={{ color: MUT, fontSize: 26, marginTop: 8 }}>real 390x844 capture, uncropped</div>
      </div>
      <div style={{ position: "absolute", right: 90, bottom: 130, fontFamily: FONT, textAlign: "right" }}>
        <div style={{ color: MUT, fontSize: 26 }}>queued on device,</div>
        <div style={{ color: TXT, fontSize: 34, fontWeight: 800 }}>synced by the server</div>
      </div>
    </AbsoluteFill>
  );
};

const Sweep: React.FC = () => {
  const f = useCurrentFrame();
  const x = interpolate(f, [480, 510], [-400, 2000], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const o = (1 - interpolate(f, [510, 525], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" })) * interpolate(f, [478, 486], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return <div style={{ position: "absolute", bottom: 120, left: x, width: 340, height: 5, background: ACCENT, opacity: o, borderRadius: 3 }} />;
};

const Closer: React.FC = () => (
  <AbsoluteFill style={{ backgroundColor: BG, fontFamily: FONT }}>
    <Img src={staticFile("stills/tray.jpg")} style={{ position: "absolute", width: "100%", height: "100%", objectFit: "cover", opacity: 0.28 }} />
    <div style={{ position: "absolute", left: 0, right: 0, bottom: 150, textAlign: "center" }}>
      <div style={{ color: ACCENT, fontSize: 30, letterSpacing: 10, fontWeight: 800 }}>TRACELOOP</div>
      <div style={{ color: TXT, fontSize: 76, fontWeight: 800, marginTop: 18 }}>Knowledge that never gets lost.</div>
      <div style={{ color: MUT, fontSize: 30, marginTop: 22 }}>Built with Meta AI · github.com/douglasparedes/traceLoop</div>
    </div>
  </AbsoluteFill>
);

/** Final: 360+600+990+690+660+600+870+240+120+120+150 = 5400. */
export const HackathonFilm: React.FC<FilmProps> = ({ voiceoverSrc, musicOn }) => (
  <AbsoluteFill>
    <Sequence from={0} durationInFrames={360}><Hook /></Sequence>
    <Sequence from={360} durationInFrames={360}><Full src="clips/g2a.mp4" len={360} label={["02", "Upload the real task", "demostration.mp4, genuine progress"]} /></Sequence>
    <Sequence from={720} durationInFrames={240}><Full src="clips/g2b.mp4" len={240} label={["02", "Processing complete", "live pipeline, ninety seconds"]} /></Sequence>
    <Sequence from={960} durationInFrames={990}><Full src="clips/g3.mp4" len={990} label={["03", "Meta AI processing", "per-stage provenance, live Spark"]} /></Sequence>
    <Sequence from={1950} durationInFrames={690}><Full src="clips/g4.mp4" len={690} label={["04", "Inspect and correct", "expert authors every step"]} /></Sequence>
    <Sequence from={2640} durationInFrames={660}><Full src="clips/g5.mp4" len={660} label={["05", "Usable instructions", "three formats, regenerated"]} /></Sequence>
    <Sequence from={3300} durationInFrames={600}>
      <AbsoluteFill style={{ backgroundColor: BG }}>
        <Push len={600} to={1.04}><OffthreadVideo src={staticFile("clips/g6.mp4")} style={{ width: "100%", height: "100%", objectFit: "cover" }} /></Push>
        <Sweep />
        <Chyron index="06" title="Human verification" sub="reviewer submits and approves" />
      </AbsoluteFill>
    </Sequence>
    <Sequence from={3900} durationInFrames={870}><Field /></Sequence>
    <Sequence from={4770} durationInFrames={240}><Full src="clips/g8a.mp4" len={240} label={["08a", "Field feedback", "step marked confusing"]} /></Sequence>
    <Sequence from={5010} durationInFrames={120}><Full src="clips/h8b.mp4" len={120} label={["08b", "Improvement proposal", "live Spark, quoted verbatim"]} /></Sequence>
    <Sequence from={5130} durationInFrames={120}><Full src="clips/h8c.mp4" len={120} label={["08c", "Approved revision", "improvement approved"]} /></Sequence>
    <Sequence from={5250} durationInFrames={150}><Closer /></Sequence>
    {musicOn !== false ? (<Sequence from={0} durationInFrames={5400}><Audio src={staticFile("audio/music.wav")} volume={0.14} /></Sequence>) : null}
    <Sequence from={925} durationInFrames={20}><Audio src={staticFile("audio/up.wav")} volume={0.4} /></Sequence>
    <Sequence from={3810} durationInFrames={30}><Audio src={staticFile("audio/ok.wav")} volume={0.4} /></Sequence>
    <Sequence from={4590} durationInFrames={30}><Audio src={staticFile("audio/sync.wav")} volume={0.4} /></Sequence>
    {voiceoverSrc ? (<Sequence from={0} durationInFrames={5400}><Audio src={voiceoverSrc} /></Sequence>) : null}
  </AbsoluteFill>
);

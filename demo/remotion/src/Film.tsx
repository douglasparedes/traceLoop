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

/* Lower-third chapter label: names the real artifact, fades after ~90f. */
const Label: React.FC<{ title: string; sub: string }> = ({ title, sub }) => {
  const f = useCurrentFrame();
  const o =
    interpolate(f, [0, 10], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }) *
    (1 - interpolate(f, [80, 95], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }));
  return (
    <div style={{ position: "absolute", left: 72, bottom: 54, opacity: o, fontFamily: FONT, display: "flex", alignItems: "center", gap: 18 }}>
      <div style={{ width: 8, height: 64, background: ACCENT, borderRadius: 4 }} />
      <div>
        <div style={{ color: TXT, fontWeight: 800, fontSize: 36 }}>{title}</div>
        <div style={{ color: MUT, fontSize: 24 }}>{sub}</div>
      </div>
    </div>
  );
};

/* Guided camera: deterministic scale + pan over a real app shot.
   Optional punch: static close-up centered at (cx,cy) with scale s —
   a camera move over real pixels (used to exclude unrelated rows). */
const Shot: React.FC<{ src: string; len: number; from?: number; to?: number; x?: number; y?: number; label?: [string, string]; punch?: { s: number; cx: number; cy: number }; still?: boolean }> = ({
  src, len, from = 1, to = 1.03, x = 0, y = 0, label, punch, still = false,
}) => {
  const f = useCurrentFrame();
  const media = still
    ? <Img src={staticFile(src)} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
    : <OffthreadVideo src={staticFile(src)} style={{ width: "100%", height: "100%", objectFit: "cover" }} />;
  if (punch) {
    // screen = scale * take + t  =>  t = center - scale * takePoint
    const tx = 960 - punch.s * punch.cx;
    const ty = 540 - punch.s * punch.cy;
    return (
      <AbsoluteFill style={{ backgroundColor: BG }}>
        <div style={{ width: "100%", height: "100%", transform: `translate(${tx}px, ${ty}px) scale(${punch.s})`, transformOrigin: "top left" }}>
          {media}
        </div>
        {label ? <Label title={label[0]} sub={label[1]} /> : null}
      </AbsoluteFill>
    );
  }
  const z = interpolate(f, [0, len], [from, to], { extrapolateRight: "clamp" });
  const dx = interpolate(f, [0, len], [0, x], { extrapolateRight: "clamp" });
  const dy = interpolate(f, [0, len], [0, y], { extrapolateRight: "clamp" });
  return (
    <AbsoluteFill style={{ backgroundColor: BG }}>
      <div style={{ width: "100%", height: "100%", transform: `scale(${z}) translate(${dx}px, ${dy}px)` }}>
        <OffthreadVideo src={staticFile(src)} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
      </div>
      {label ? <Label title={label[0]} sub={label[1]} /> : null}
    </AbsoluteFill>
  );
};

/* Emphasis ring drawn over a field being edited (documentary focus aid). */
const CursorRing: React.FC<{ cx: number; cy: number; r?: number; at?: number; hold?: number }> = ({ cx, cy, r = 46, at = 0, hold = 90 }) => {
  const f = useCurrentFrame();
  const o =
    interpolate(f, [at, at + 12], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }) *
    (1 - interpolate(f, [at + hold, at + hold + 18], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }));
  const pulse = 1 + 0.06 * Math.sin((f * Math.PI) / 15);
  return (
    <div style={{
      position: "absolute", left: cx - r * pulse, top: cy - r * pulse,
      width: r * 2 * pulse, height: r * 2 * pulse, borderRadius: "50%",
      border: "3px solid rgba(255,176,32,0.9)", opacity: o,
      boxShadow: "0 0 24px rgba(255,176,32,0.35)",
    }} />
  );
};

/* Overlay cross-dissolve into the next shot's first frames (no duration cost). */
const Dissolve: React.FC<{ from: number; dur: number; src: string }> = ({ from, dur, src }) => (
  <Sequence from={from} durationInFrames={dur}>
    <DissolveInner dur={dur} src={src} />
  </Sequence>
);
const DissolveInner: React.FC<{ dur: number; src: string }> = ({ dur, src }) => {
  const f = useCurrentFrame();
  return (
    <AbsoluteFill style={{ opacity: interpolate(f, [0, dur], [0, 1]), backgroundColor: BG }}>
      <OffthreadVideo src={staticFile(src)} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
    </AbsoluteFill>
  );
};

const Hook: React.FC = () => {
  const f = useCurrentFrame();
  const z = interpolate(f, [0, 360], [1, 1.14], { extrapolateRight: "clamp" });
  return (
    <AbsoluteFill style={{ backgroundColor: BG, alignItems: "center", justifyContent: "center", fontFamily: FONT }}>
      <div style={{ width: 609, height: 1080, overflow: "hidden", transform: `scale(${z})` }}>
        <OffthreadVideo src={staticFile("clips/g1.mp4")} style={{ width: "100%", height: "100%", objectFit: "fill" }} />
      </div>
      <div style={{ position: "absolute", left: 110, bottom: 110, opacity: interpolate(f, [300, 355], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }) }}>
        <div style={{ color: ACCENT, fontSize: 28, letterSpacing: 6, fontWeight: 800 }}>A REAL TASK, RECORDED</div>
        <div style={{ color: TXT, fontSize: 72, fontWeight: 800, marginTop: 12 }}>Expert knowledge should not disappear.</div>
      </div>
    </AbsoluteFill>
  );
};

const PhoneField: React.FC = () => (
  <AbsoluteFill style={{ backgroundColor: BG, display: "flex", flexDirection: "row", alignItems: "center", justifyContent: "center" }}>
    <div style={{ width: 500, height: 1080, borderLeft: "1px solid rgba(255,255,255,0.14)", borderRight: "1px solid rgba(255,255,255,0.14)" }}>
      <OffthreadVideo src={staticFile("clips/r7a.mp4")} style={{ width: "100%", height: "100%", objectFit: "fill" }} />
    </div>
    <div style={{ position: "absolute", left: 90, top: 130, fontFamily: FONT }}>
      <div style={{ color: ACCENT, fontSize: 28, letterSpacing: 5, fontWeight: 800 }}>FIELD EXECUTION</div>
      <div style={{ color: TXT, fontSize: 42, fontWeight: 800, marginTop: 10 }}>Works without signal.</div>
      <div style={{ color: MUT, fontSize: 26, marginTop: 8 }}>real phone capture, uncropped</div>
    </div>
    <div style={{ position: "absolute", right: 90, bottom: 130, fontFamily: FONT, textAlign: "right" }}>
      <div style={{ color: MUT, fontSize: 26 }}>queued on device,</div>
      <div style={{ color: TXT, fontSize: 34, fontWeight: 800 }}>confirmed by the server</div>
    </div>
  </AbsoluteFill>
);

const VideoGuideMoment: React.FC = () => {
  const f = useCurrentFrame();
  const z = interpolate(f, [0, 210], [1, 1.05], { extrapolateRight: "clamp" });
  return (
    <AbsoluteFill style={{ backgroundColor: BG, alignItems: "center", justifyContent: "center", fontFamily: FONT }}>
      <div style={{ width: 1600, height: 900, overflow: "hidden", borderRadius: 18, transform: `scale(${z})`, border: "1px solid rgba(255,255,255,0.16)" }}>
        <OffthreadVideo src={staticFile("clips/r5c.mp4")} style={{ width: "100%", height: "100%", objectFit: "fill" }} />
      </div>
      <div style={{ position: "absolute", left: 0, right: 0, bottom: 46, textAlign: "center" }}>
        <div style={{ color: TXT, fontSize: 32, fontWeight: 800 }}>The app renders its own guide video — captioned, since the source has no narration.</div>
      </div>
    </AbsoluteFill>
  );
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

/**
 * Master: 360+450+990+720+750+(72+240+288)+750+600+180 = 5400.
 * Dissolves are overlays (zero duration cost). Punches are static close-ups
 * over real pixels (S6a excludes unrelated queue rows; S8b the same;
 * S8c isolates the archival REV-5 card).
 */
export const HackathonFilm: React.FC<FilmProps> = ({ voiceoverSrc, musicOn }) => (
  <AbsoluteFill>
    {/* S1 hook 0-360 */}
    <Sequence from={0} durationInFrames={360}><Hook /></Sequence>
    <Dissolve from={350} dur={10} src="clips/r2a.mp4" />
    {/* S2 upload 360-810 */}
    <Sequence from={360} durationInFrames={360}>
      <AbsoluteFill style={{ backgroundColor: BG }}>
        <Shot src="clips/r2a.mp4" len={360} from={1.06} to={1.0} label={["Upload", "the same recording becomes the input"]} />
        <CursorRing cx={1050} cy={560} at={120} hold={120} />
      </AbsoluteFill>
    </Sequence>
    <Sequence from={720} durationInFrames={90}><Shot src="clips/r2b.mp4" len={90} label={["Processing", "the pipeline runs; waiting is condensed"]} /></Sequence>
    {/* S3 AI understanding 810-1800 */}
    <Sequence from={810} durationInFrames={990}>
      <Shot src="clips/r3.mp4" len={990} to={1.04} label={["Meta AI processing", "live Spark · transcription pending · segmentation skipped"]} />
    </Sequence>
    {/* S4 correction 1800-2520: honest empty hold, then the real edit */}
    <Sequence from={1800} durationInFrames={60}>
      <AbsoluteFill style={{ backgroundColor: BG }}>
        <Img src={staticFile("clips/r4hold.png")} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
        <Label title="Expert correction" sub="the AI found no steps — the expert enters what the footage shows" />
      </AbsoluteFill>
    </Sequence>
    <Sequence from={1860} durationInFrames={660}>
      <AbsoluteFill style={{ backgroundColor: BG }}>
        <Shot src="clips/r4.mp4" len={660} to={1.03} />
        <CursorRing cx={1290} cy={770} r={60} at={60} hold={150} />
      </AbsoluteFill>
    </Sequence>
    {/* S5 guides 2520-3270 */}
    <Sequence from={2520} durationInFrames={300}><Shot src="clips/r5a.mp4" len={300} label={["Usable guides", "every generation kept · time ranges honestly unavailable"]} /></Sequence>
    <Sequence from={2820} durationInFrames={240}><Shot src="clips/r5b.mp4" len={240} label={["Video guide", "attempted · honestly failed · then fixed"]} /></Sequence>
    <Sequence from={3060} durationInFrames={210}><VideoGuideMoment /></Sequence>
    {/* S6 verification 3270-3870: submitted still, live approve act (right-pane
        punch excludes unrelated queue rows), approved card */}
    <Sequence from={3270} durationInFrames={72}>
      <AbsoluteFill style={{ backgroundColor: BG }}>
        <Img src={staticFile("stills/submitted.png")} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
        <Label title="Human verification" sub="the draft is submitted for review" />
      </AbsoluteFill>
    </Sequence>
    <Sequence from={3342} durationInFrames={240}>
      <Shot src="clips/r6a.mp4" len={240} punch={{ s: 2.0, cx: 1350, cy: 770 }} label={["Human verification", "reviewed on camera — never automatic"]} />
    </Sequence>
    <Sequence from={3582} durationInFrames={288}><Shot src="clips/r6b.mp4" len={288} to={1.03} label={["Approved", "immutable — only superseded, never edited"]} /></Sequence>
    <Dissolve from={3858} dur={12} src="clips/r7a.mp4" />
    {/* S7 offline 3870-4620 */}
    <Sequence from={3870} durationInFrames={660}><PhoneField /></Sequence>
    <Sequence from={4530} durationInFrames={90}><Shot src="clips/r7b.mp4" len={90} label={["Saved for offline", "verified in local storage on the device"]} /></Sequence>
    {/* S8 feedback loop 4620-5220 */}
    <Sequence from={4620} durationInFrames={240}>
      <Shot src="clips/r8a.mp4" len={240} x={-40} label={["Field feedback", "the whisking question, recorded verbatim"]} />
    </Sequence>
    <Sequence from={4860} durationInFrames={120}>
      <Shot src="stills/r8bhold.png" still len={120} punch={{ s: 2.0, cx: 1400, cy: 600 }} label={["Improvement proposal", "live Spark quotes the technician · medium confidence"]} />
    </Sequence>
    <Sequence from={4980} durationInFrames={120}>
      <Shot src="clips/r8b.mp4" len={120} punch={{ s: 2.0, cx: 1400, cy: 600 }} />
    </Sequence>
    <Sequence from={5100} durationInFrames={120}><Shot src="clips/h8c.mp4" len={120} punch={{ s: 3.0, cx: 750, cy: 555 }} label={["Approved", "the fix becomes the approved revision"]} /></Sequence>
    {/* S9 closer 5220-5400 */}
    <Sequence from={5220} durationInFrames={180}><Closer /></Sequence>
    {musicOn !== false ? (<Sequence from={0} durationInFrames={5400}><Audio src={staticFile("audio/music.wav")} volume={0.14} /></Sequence>) : null}
    <Sequence from={780} durationInFrames={20}><Audio src={staticFile("audio/up.wav")} volume={0.4} /></Sequence>
    <Sequence from={3000} durationInFrames={30}><Audio src={staticFile("audio/ok.wav")} volume={0.4} /></Sequence>
    <Sequence from={3760} durationInFrames={12}><Audio src={staticFile("audio/ok.wav")} volume={0.35} /></Sequence>
    <Sequence from={4450} durationInFrames={30}><Audio src={staticFile("audio/sync.wav")} volume={0.4} /></Sequence>
    {voiceoverSrc ? (<Sequence from={0} durationInFrames={5400}><Audio src={voiceoverSrc} /></Sequence>) : null}
  </AbsoluteFill>
);

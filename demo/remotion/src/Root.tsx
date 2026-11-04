import React from "react";
import { Composition, registerRoot } from "remotion";
import { FilmPropsSchema, HackathonFilm } from "./Film";

export const RemotionRoot: React.FC = () => (
  <Composition
    id="TraceLoopHackathon180"
    component={HackathonFilm}
    schema={FilmPropsSchema}
    durationInFrames={5400}
    fps={30}
    width={1920}
    height={1080}
    defaultProps={{ voiceoverSrc: null, musicOn: true }}
    calculateMetadata={() => ({ durationInFrames: 5400, fps: 30 as const, width: 1920, height: 1080 })}
  />
);

registerRoot(RemotionRoot);

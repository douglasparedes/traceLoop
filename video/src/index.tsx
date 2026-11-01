// Remotion entry: registers ProcedureVideo with dynamic duration from props.
// Per docs/remotion/markup-SKILL.md: calculateMetadata derives duration;
// Zod schema validates server-generated props at the render boundary.
import React from "react";
import { Composition, registerRoot } from "remotion";
import { ProcedureVideo, VideoPropsSchema } from "./ProcedureVideo";

export const RemotionRoot: React.FC = () => {
  return (
    <Composition
      id="ProcedureVideo"
      component={ProcedureVideo}
      schema={VideoPropsSchema}
      fps={30}
      width={1280}
      height={720}
      durationInFrames={150}
      calculateMetadata={({ props }) => {
        const parsed = VideoPropsSchema.parse(props);
        return {
          durationInFrames: Math.max(30, parsed.totalFrames),
          fps: parsed.fps,
          width: parsed.width,
          height: parsed.height,
        };
      }}
      defaultProps={{
        title: "TraceLoop guide",
        fps: 30,
        width: 1280,
        height: 720,
        voiceover: null,
        voiceoverFrames: 0,
        scenes: [],
        totalFrames: 150,
      }}
    />
  );
};

registerRoot(RemotionRoot);

# Render instructions (exact)

```powershell
cd demo/remotion
node ..\..\video\node_modules\@remotion\cli\remotion-cli.js render `
  src/Root.tsx TraceLoopHackathon180 `
  --public-dir=public ..\output\traceloop-hackathon-180s.mp4 `
  --browser-executable="C:\Program Files\Google\Chrome\Application\chrome.exe" `
  --overwrite
```

Notes:
- System Chrome is required: the default bundled headless shell has no system
  fonts (chyron/title cards fall back to serif). App footage is pre-rendered
  and unaffected.
- `voiceoverSrc` defaults to `null` → no Audio element is mounted. To add the
  owner's narration later: pass `--props='{"voiceoverSrc":"..."}'` (public-dir
  relative) — frame count stays 5400 (`calculateMetadata` returns 5400
  regardless of media).
- No music, no TTS, no speech in this export by design.

## Verify (hard gates)

```powershell
ffprobe -v error -select_streams v:0 -show_entries stream=width,height,avg_frame_rate,codec_name,pix_fmt,nb_frames -show_entries format=duration,size -of default=noprint_wrappers=1 demo/output/traceloop-hackathon-180s.mp4
ffprobe -v error -count_frames -select_streams v:0 -show_entries stream=nb_read_frames -of csv=p=0 demo/output/traceloop-hackathon-180s.mp4
ffprobe -v error -select_streams a -show_entries stream=codec_name -of csv=p=0 demo/output/traceloop-hackathon-180s.mp4  # must print nothing
```

Gates: 1920×1080, 30/1 fps, h264 yuv420p, nb_read_frames = 5400,
duration = 180.000 s video stream, **no audio streams**.

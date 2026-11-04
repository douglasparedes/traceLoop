# Render instructions (exact, final film)

> Render runs from a Temp copy (`$env:TEMP\film-build`) because the repo lives
> in a cloud-synced tree whose files intermittently 404 mid-render. Copy
> `demo/remotion/{src,public,package.json,tsconfig.json}` to Temp, junction
> `node_modules` → `video/node_modules`, render, move the MP4 back.

```powershell
cd $env:TEMP\film-build
node node_modules/@remotion/cli/remotion-cli.js render src/Root.tsx TraceLoopHackathon180 --public-dir=public $env:TEMP/final-180s.mp4 --browser-executable="C:\Program Files\Google\Chrome\Application\chrome.exe" --overwrite --props=props.json
```

`props.json` = `{"voiceoverSrc":null}` (no voice Audio mounted; music stays;
`calculateMetadata` returns 5400 regardless — frame count cannot drift).

Owner voiceover later: record into the 11 windows of
FINAL_VOICEOVER_TIMELINE.json, save as `public/audio/voiceover.wav`,
re-render with `--props={"voiceoverSrc":"audio/voiceover.wav"}`.

## Verify (hard gates)

```powershell
ffprobe -v error -select_streams v:0 -show_entries stream=width,height,avg_frame_rate,codec_name,pix_fmt,nb_frames -show_entries format=duration,size -of default=noprint_wrappers=1 demo/output/traceloop-hackathon-final-180s.mp4
ffprobe -v error -count_frames -select_streams v:0 -show_entries stream=nb_read_frames -of csv=p=0 demo/output/traceloop-hackathon-final-180s.mp4
ffprobe -v error -select_streams a -show_entries stream=codec_name -of csv=p=0 demo/output/traceloop-hackathon-final-180s.mp4
```

Gates: 1920×1080 · 30/1 · h264 yuv420p · nb_read_frames 5400 ·
duration 180.000000 · audio = 1 AAC stream (music+SFX, no voice).
Normalize range first if needed:
`ffmpeg -i IN -vf scale=in_range=full:out_range=limited -pix_fmt yuv420p -color_range tv -c:a aac -movflags +faststart OUT`.

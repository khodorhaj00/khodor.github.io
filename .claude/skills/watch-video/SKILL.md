---
name: watch-video
description: >
  MUST USE when the user shares a video URL (YouTube, youtu.be, etc.) or a
  local video/audio file and wants Claude to watch, see, hear, listen,
  summarize, transcribe, review, or answer questions about it — e.g.
  "watch this video", "what does he say at 3:20", "summarize this tutorial",
  "what machine is shown here". Gives Claude both AUDIO (subtitles/Whisper
  transcript) and VISION (extracted frames read as images).
metadata:
  depends: agent-reach (github.com/Panniantong/Agent-Reach), yt-dlp, ffmpeg
---

# Watch Video — hear + see any video

Combine two channels, then answer from both:
- **HEAR** = full transcript with timestamps (subtitles, or Whisper fallback)
- **SEE** = frames sampled from the video, read with the Read tool (vision)

All temp output goes in the scratchpad dir (or `/tmp/vid/`), never the repo.

## 0. Tooling check

```bash
export PATH="$HOME/.local/bin:$PATH"
command -v yt-dlp || bash .claude/scripts/setup-video-tools.sh
```

## 1. Metadata first (always)

```bash
yt-dlp --dump-json "URL" > /tmp/vid/meta.json   # then read title, duration, chapters
```

Use `duration` to plan frame sampling; use `chapters` to target sections.

## 2. HEAR — transcript

```bash
# Subtitles only, no video download (en + ar; add langs as needed)
yt-dlp --write-sub --write-auto-sub --sub-lang "en.*,ar.*" --skip-download \
  -o "/tmp/vid/%(id)s" "URL"
# Auto-subs repeat lines; flatten before reading:
sed -E 's/<[^>]+>//g' /tmp/vid/*.vtt | awk 'NF && !seen[$0]++' > /tmp/vid/transcript.txt
```

No subtitles at all → Whisper fallback (needs `GROQ_API_KEY` env secret, free
key at console.groq.com, or `OPENAI_API_KEY`):

```bash
agent-reach transcribe "URL"            # YouTube/public URL
agent-reach transcribe /path/audio.mp3  # local file
```

## 3. SEE — frames

Short video (≤ ~10 min): grab the whole thing at low res, sample ≤16 frames.

```bash
yt-dlp -f "wv*[height>=240][height<=480]/wv*/w" -o "/tmp/vid/v.%(ext)s" "URL"
D=$(ffprobe -v error -show_entries format=duration -of csv=p=0 /tmp/vid/v.*)
ffmpeg -y -loglevel error -i /tmp/vid/v.* \
  -vf "fps=1/$(python3 -c "import math;print(max(1,math.ceil($D/16)))"),scale=640:-2" \
  /tmp/vid/f_%02d.jpg
```

Long video or specific moment: download only the relevant section —

```bash
yt-dlp -f "wv*[height<=480]/w" --download-sections "*00:03:00-00:03:40" \
  -o "/tmp/vid/clip.%(ext)s" "URL"
ffmpeg -y -loglevel error -i /tmp/vid/clip.* -vf "fps=1/2,scale=640:-2" /tmp/vid/s_%02d.jpg
```

Then **Read the .jpg files** (several per message is fine). Match what you see
against transcript timestamps before answering. For "what happens at MM:SS"
questions, always pull frames at that timestamp — don't answer from audio alone.

## 4. Local video files

Same as above, skipping yt-dlp: ffmpeg frames + `ffmpeg -i in.mp4 -vn -acodec
libmp3lame /tmp/vid/a.mp3` then `agent-reach transcribe /tmp/vid/a.mp3`.

## Failure modes

- `Tunnel connection failed: 403 Forbidden` → the cloud environment's network
  policy blocks the host. Tell the user to allow `youtube.com` +
  `googlevideo.com` (or raise the network access level) in the environment
  settings — do not retry or route around it.
- Bot-check / empty subs on YouTube → retry once, then Whisper fallback.
- Bilibili: never yt-dlp (hard 412-blocked); see the agent-reach skill.
- Other platforms (Twitter, Instagram, RSS, web pages): use the agent-reach
  skill routing table.

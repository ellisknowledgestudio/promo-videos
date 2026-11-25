# Ellis Knowledge Studio – promo reels

Builds the 9:16 promo reel for a classroom tool automatically:
Eddie Stirling voiceover (ElevenLabs), a hands-free recording of the tool in demo mode,
all placed in the Ellis Knowledge reel template with captions.

- `jobs/<slug>.json` – one per video (captions, pauses, timed clicks). Pushing one starts a build.
- `make_reel.py` – the builder (Playwright + ffmpeg + ElevenLabs).
- `assets/bg.png` – the empty-frame background exported from Canva
  ("AUTOMATION – Ellis reel background").
- `results/<slug>.json` – written by the build: the public video link, or the error log.
- Finished videos are published as GitHub releases.

Secret needed: `ELEVENLABS_API_KEY` (Text to Speech access only).

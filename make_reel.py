#!/usr/bin/env python3
"""
Ellis Knowledge Studio - automated 9:16 promo reel for a classroom tool.

    python3 make_reel.py job.json --site ./classroom-site --bg bg.png --out reel.mp4

job.json:
{
  "slug": "what-is-electricity",
  "page": "/electricity/what-is-electricity/",       # path on the classroom site
  "url_text": "https://classroom.ellisknowledgestudio.com/electricity/what-is-electricity/",
  "voice_id": "....",                                 # ElevenLabs voice
  "captions": ["What is electricity?", "Let's find out with", ...],   # spoken in order
  "steps": [ {"cap": 5, "plus": 0.2, "click": "[data-id='switch1']"}, ... ]
}
Each demo step is pinned to the moment caption number "cap" (0-based) starts being
spoken, plus "plus" seconds, so clicks always land on the words that describe them.
Any EKDemo action works: click, scroll, scrollTop, point, hide, show.

Needs: ffmpeg, Playwright (Chromium) and, for the voiceover, ELEVENLABS_API_KEY.
Without the key (or with --silent) it makes a silent test version with estimated timings.
"""
import argparse, base64, json, os, re, shutil, subprocess, sys, tempfile, threading, time, http.server, functools, urllib.request

W, H = 1080, 1920
FRAME = (66, 565, 948, 814)          # x, y, w, h of the screen window in the Canva template
REC_W, REC_H = 1000, 859             # browser viewport, same shape as the window
URL_BOX = (330, 349, 560, 130)        # area right of the link icon inside the pill
CAP_Y = 1470                         # vertical centre of the caption line


def sh(cmd):
    subprocess.run(cmd, check=True)


# ---------- voiceover -------------------------------------------------------
def tts(job, out_mp3):
    """ElevenLabs text-to-speech with character timestamps. Returns caption start/end times.
    job["pauses"] = caption numbers (0-based) followed by a pause, e.g. at the end of a sentence;
    job["pause_secs"] sets its length (default 1.0, like the hand-made voiceovers)."""
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        return None
    pauses = set(job.get("pauses", []))
    brk = f' <break time="{job.get("pause_secs", 1.0)}s" /> '
    text = ""
    for i, cap in enumerate(job["captions"]):
        text += cap + (brk if i in pauses else " ")
    body = json.dumps({
        "text": text.strip(),
        "model_id": job.get("model_id", "eleven_multilingual_v2"),
        "voice_settings": job.get("voice_settings", {"stability": 0.5, "similarity_boost": 0.75}),
    }).encode()
    req = urllib.request.Request(
        f"https://api.elevenlabs.io/v1/text-to-speech/{job['voice_id']}/with-timestamps?output_format=mp3_44100_128",
        data=body, headers={"xi-api-key": key, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        res = json.load(r)
    open(out_mp3, "wb").write(base64.b64decode(res["audio_base64"]))
    al = res.get("alignment") or res["normalized_alignment"]
    chars = "".join(al["characters"])
    starts, ends = al["character_start_times_seconds"], al["character_end_times_seconds"]
    times, pos = [], 0
    for cap in job["captions"]:
        i = chars.find(cap, pos)
        if i < 0:                       # fall back to the first word of the caption
            i = chars.find(cap.split()[0], pos)
        if i < 0:
            i = pos
        j = min(i + len(cap) - 1, len(ends) - 1)
        times.append((starts[i], ends[j]))
        pos = j + 1
    return times


def estimate(job):
    """Rough timings for a silent test (about 2.6 words a second)."""
    t, times = 0.6, []
    for cap in job["captions"]:
        d = max(0.9, len(cap.split()) / 2.6)
        times.append((t, t + d))
        t += d + 0.15
    return times


# ---------- screen recording -----------------------------------------------
def record(job, site, times, lead, total, out_webm):
    from playwright.async_api import async_playwright
    import asyncio

    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=site)
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    steps = []
    for s in job["steps"]:
        s = dict(s)
        at = times[s.pop("cap")][0] + s.pop("plus", 0.0) - 0.75   # clicks animate for 0.75 s first
        s["at"] = round(max(0.0, at), 2)
        steps.append(s)
    parts = []
    for s in steps:
        js = s.pop("js", None)
        obj = json.dumps(s)
        if js:   # custom page code, e.g. flipping a switch in a circuit
            obj = obj[:-1] + ', "action": function (el) { ' + js + ' }}'
        parts.append(obj)
    define = "EKDemo.define([" + ",\n".join(parts) + "]);"
    vid_dir = tempfile.mkdtemp()

    async def go():
        async with async_playwright() as p:
            exe = shutil.which("google-chrome") or shutil.which("chromium")
            b = await p.chromium.launch(executable_path=exe, args=["--no-sandbox"]) if exe else await p.chromium.launch()
            ctx = await b.new_context(viewport={"width": REC_W, "height": REC_H},
                                      record_video_dir=vid_dir, record_video_size={"width": REC_W, "height": REC_H})
            t0 = time.monotonic()
            pg = await ctx.new_page()
            # Block analytics in recordings
            await pg.route(re.compile(r".*googletagmanager.*"), lambda r: r.abort())
            await pg.goto(f"http://127.0.0.1:{port}{job['page']}", wait_until="load")
            await pg.wait_for_timeout(600)
            # Switch demo mode on now (the page's own demo script stayed inactive), load a fresh
            # copy of demo.js so it reads ?demo&wait=0, then define this video's timed steps.
            await pg.evaluate("() => history.replaceState(null, '', location.pathname + '?demo&wait=0')")
            await pg.add_script_tag(path=os.path.join(site, "electricity/assets/demo.js"))
            await pg.evaluate("(src) => { (new Function(src))(); }", define)
            started = time.monotonic() - t0 + 0.8          # wait=0 starts 0.8 s after define
            await pg.wait_for_timeout(int((total + 1.5) * 1000))
            await ctx.close(); await b.close()
            return started
    started = asyncio.run(go())
    httpd.shutdown()
    f = [os.path.join(vid_dir, x) for x in os.listdir(vid_dir)][0]
    shutil.move(f, out_webm)
    return started


# ---------- captions --------------------------------------------------------
def ass_time(t):
    t = max(0, t); h = int(t // 3600); m = int(t % 3600 // 60); s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def write_ass(job, times, path, offset):
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,DejaVu Serif,50,&H00000000,&H00000000,&H00FFFFFF,&H00FFFFFF,0,0,0,0,100,100,0,0,3,10,0,5,80,80,0,1
Style: Url,DejaVu Sans,23,&H0000F55C,&H0000F55C,&H00000000,&H00000000,1,0,0,0,100,100,0,0,1,0,0,4,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    total = times[-1][1] + offset + 2.5
    url = job["url_text"]
    # split the URL after the domain if it is long, like the hand-made reels
    if len(url) > 38 and ".com/" in url:
        i = url.index(".com/") + 5
        url = url[:i] + "\\N" + url[i:]
    x, y = URL_BOX[0], URL_BOX[1] + URL_BOX[3] // 2
    lines.append(f"Dialogue: 0,{ass_time(0)},{ass_time(total)},Url,,0,0,0,,{{\\an4\\pos({x},{y})}}{url}")
    for i, cap in enumerate(job["captions"]):
        a = times[i][0] + offset
        b = (times[i + 1][0] + offset) if i + 1 < len(times) else times[i][1] + offset + 1.2
        txt = cap.replace("{", "(").replace("}", ")")
        lines.append(f"Dialogue: 1,{ass_time(a)},{ass_time(b)},Cap,,0,0,0,,{{\\an5\\pos({W//2},{CAP_Y})}}{txt}")
    open(path, "w").write(head + "\n".join(lines) + "\n")
    return total


# ---------- compose ---------------------------------------------------------
def compose(bg, webm, mp3, ass, rec_start, voice_offset, total, out):
    x, y, w, h = FRAME
    trim = max(0.0, rec_start - voice_offset)
    inputs = ["-loop", "1", "-i", bg, "-ss", f"{trim:.2f}", "-i", webm]
    if mp3:
        inputs += ["-itsoffset", f"{voice_offset:.2f}", "-i", mp3]
    fc = (f"[1:v]scale={w}:{h}:flags=lanczos,setsar=1,fps=30[rec];"
          f"[0:v]scale={W}:{H},setsar=1[bg];"
          f"[bg][rec]overlay={x}:{y}:shortest=0[v0];"
          f"[v0]subtitles={ass}:fontsdir=/usr/share/fonts[v]")
    cmd = ["ffmpeg", "-y", "-v", "error"] + inputs + ["-filter_complex", fc, "-map", "[v]"]
    if mp3:
        cmd += ["-map", "2:a", "-c:a", "aac", "-b:a", "160k"]
    cmd += ["-t", f"{total:.2f}", "-r", "30", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", out]
    sh(cmd)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("job"); ap.add_argument("--site", required=True); ap.add_argument("--bg", required=True)
    ap.add_argument("--out", required=True); ap.add_argument("--silent", action="store_true")
    a = ap.parse_args()
    job = json.load(open(a.job))
    work = tempfile.mkdtemp()
    mp3 = os.path.join(work, "voice.mp3")
    times = None if a.silent else tts(job, mp3)
    if times is None:
        mp3 = None; times = estimate(job)
        print("No voiceover (silent test with estimated timings)")
    voice_offset = 0.4
    total_voice = times[-1][1] + 1.5
    webm = os.path.join(work, "rec.webm")
    rec_start = record(job, a.site, times, voice_offset, total_voice, webm)
    ass = os.path.join(work, "caps.ass")
    total = write_ass(job, times, ass, voice_offset)
    compose(a.bg, webm, mp3, ass, rec_start, voice_offset, total, a.out)
    json.dump({"captions": [[c, t[0], t[1]] for c, t in zip(job["captions"], times)]},
              open(a.out + ".timings.json", "w"), indent=1)
    print("Made", a.out)


if __name__ == "__main__":
    main()

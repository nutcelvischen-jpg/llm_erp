"""把 record_demo_auto.py 錄的畫面配上旁白與字幕，輸出 llm_erp_demo_narrated.mp4 與 .srt。

流程：旁白逐句送 OpenRouter Gemini TTS（逐句才拿得到準確的字幕時間）→ 依 timeline.json 剪出每題畫面
（AI 思考的空白時間壓縮、結果畫面停住等旁白講完）→ 字幕畫成 PNG 疊上去 → 混音輸出。

前置：先跑過 scripts/record_demo_auto.py（產生 raw 影片與 timeline.json），且系統有 ffmpeg。
執行：
  uv run --with pillow python scripts/make_demo_video.py --key-file /path/to/OPR-KEY.txt
金鑰只在執行時讀取（也可用環境變數 OPENROUTER_API_KEY），不寫進程式碼、不印出。
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import wave
from pathlib import Path

import httpx
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
REC = ROOT / "data" / "demo_recordings"
WORK = REC / "_work"
W, H = 1440, 900
SR = 24000  # Gemini TTS 固定輸出 24 kHz、單聲道、16-bit PCM
TTS_URL = "https://openrouter.ai/api/v1/audio/speech"
TTS_MODEL = "google/gemini-3.8-flash-tts"
LEAD, GAP, TAIL = 0.4, 0.3, 0.7  # 每段開頭靜音、句間停頓、結尾停頓（秒）

# 旁白（台灣用語、專業語氣）。key 對應 timeline.json；數字都取自畫面，換資料要同步改。
NARRATION = [
    ("01_dashboard", "各位好，這是部署在公司內網的 ERP 智慧助理。首頁儀表板直接讀取資料庫，不經過 AI，關鍵指標一眼就能掌握。"),
    ("02_margin_drop", "接著用中文直接提問：今年毛利跟去年同期比，表現如何？系統辨識出這是同期比較的標準查詢，整體毛利比去年同期少了百分之六，其中鴻遠機械下滑最多，減少約八十三萬七千元。右側可以展開查詢的 SQL，每個數字都能稽核。"),
    ("03_revenue_trend", "再追問鴻遠機械最近一年的每月營收。系統自動畫出折線圖，可以清楚看到從六月開始，營收出現明顯的斷崖式下滑。"),
    ("04_contract_merging", "老闆最想知道的是，鴻遠機械今年拿得到折讓嗎？這一題要同時用到 ERP 的數字與合約文件。系統查出今年營收約一千零十九萬元，再從銷售合約第三頁找到條款，門檻是兩千萬元，因此今年拿不到折讓，並附上文件出處供查證。"),
    ("05_dead_stock", "接著是呆滯庫存。超過一百八十天沒有異動的料號共有十二個，庫存金額合計約兩百九十萬元，其中客製件零零八的金額最高。"),
    ("06_shortage_alert", "再來是缺料預警。依照目前待出貨的訂單，有三個料號庫存不足，系統同時算出建議採購量，採購人員可以直接據此下單。"),
    ("07_ar_aging", "最後是應收帳款的帳齡分佈。未收款合計約一千一百九十萬元，其中逾期六十一天以上的有十八張，約五十八萬元，需要優先追款。"),
    ("_outro", "以上所有數字，都由公司既定的查詢程式，在唯讀資料庫中取得。AI 只負責理解問題與說明結果，全程在地端執行，資料不外流。謝謝大家。"),
]


def load_key(key_file):
    if os.environ.get("OPENROUTER_API_KEY"):
        return os.environ["OPENROUTER_API_KEY"]
    if key_file:
        m = re.search(r"sk-or-[A-Za-z0-9_-]+", Path(key_file).read_text(encoding="utf-8", errors="ignore"))
        if m:
            return m.group(0)
    sys.exit("找不到 OpenRouter 金鑰：請用 --key-file 或設定 OPENROUTER_API_KEY")


def split_sentences(text):
    return [s for s in re.findall(r"[^。！？]+[。！？]?", text) if s.strip()]


def tts(key, voice, text):
    """回傳 PCM bytes；以文字與聲音做快取，重跑不會重複扣費。"""
    WORK.mkdir(parents=True, exist_ok=True)
    cache = WORK / f"tts_{hashlib.sha1((voice + '|' + text).encode()).hexdigest()[:16]}.pcm"
    if cache.exists():
        return cache.read_bytes()
    for attempt in range(3):
        try:
            r = httpx.post(
                TTS_URL,
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={"model": TTS_MODEL, "voice": voice, "input": text},
                timeout=120,
            )
            if r.status_code == 200 and r.headers.get("content-type", "").startswith("audio/pcm"):
                cache.write_bytes(r.content)
                return r.content
            err = r.text[:200]
        except httpx.HTTPError as e:
            err = str(e)[:200]
        print(f"  TTS 失敗（第 {attempt + 1} 次）：{err}")
        time.sleep(3)
    sys.exit(f"TTS 連續失敗：{text[:20]}…")


def silence(sec):
    return b"\x00\x00" * int(SR * sec)


def pcm_sec(b):
    return len(b) / 2 / SR


def chunk_subtitles(sentence, t0, dur):
    """一句旁白依逗號切成字幕塊，依字數分配時間；單塊過長再平均切開。"""
    parts = [p for p in re.split(r"[，、：；]", sentence) if p.strip()]
    chunks = []
    for p in parts:
        p = re.sub(r"[。！？]", "", p).strip()
        n = -(-len(p) // 26)
        size = -(-len(p) // n)
        chunks += [p[i:i + size] for i in range(0, len(p), size)]
    total = sum(len(c) for c in chunks) or 1
    out, t = [], t0
    for c in chunks:
        d = dur * len(c) / total
        out.append((t, t + d, c))
        t += d
    return out


def pick_font(size):
    cands = list((Path("/System/Library/AssetsV2")).glob("**/PingFang.ttc"))
    if not cands:
        sys.exit("找不到 PingFang 字型（macOS）；請改用其他含繁體字的字型")
    for i in range(30):
        try:
            f = ImageFont.truetype(str(cands[0]), size, index=i)
        except OSError:
            break
        name = " ".join(f.getname())
        if "PingFang TC" in name and "Medium" in name:
            return f
    return ImageFont.truetype(str(cands[0]), size)


def subtitle_png(text, font, path):
    pad_x, pad_y = 26, 12
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    l, t, r, b = probe.textbbox((0, 0), text, font=font)
    w, h = r - l + pad_x * 2, b - t + pad_y * 2 + 6
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.text((pad_x - l, pad_y - t + 2), text, font=font, fill=(255, 255, 255, 255))
    im.save(path)
    return w, h


BAR_H = 84


def bar_png(path):
    """整段影片固定的底部字幕條（蓋住輸入欄，避免字幕空檔時輸入欄閃現）。"""
    Image.new("RGBA", (W, BAR_H), (8, 16, 32, 255)).save(path)


def srt_time(t):
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        sys.exit(f"ffmpeg 失敗：{' '.join(map(str, cmd))[:200]}\n{r.stderr[-800:]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--key-file")
    ap.add_argument("--voice", default="Kore", help="Gemini 聲音名稱，女聲如 Kore、Sulafat、Zephyr、Leda")
    ap.add_argument("--out", default=str(REC / "llm_erp_demo_narrated.mp4"))
    a = ap.parse_args()

    tl = json.loads((REC / "timeline.json").read_text(encoding="utf-8"))
    raw = next(iter((REC / "raw_video").glob("*.webm")), None) or REC / "llm_erp_demo.webm"
    if not raw.exists():
        sys.exit("找不到錄影檔，請先跑 scripts/record_demo_auto.py")
    key = load_key(a.key_file)
    WORK.mkdir(parents=True, exist_ok=True)

    audio, subs, scene_files, t_cursor = b"", [], [], 0.0
    for idx, (sid, text) in enumerate(NARRATION):
        sents = split_sentences(text)
        seg = silence(LEAD)
        cues = []
        for s in sents:
            pcm = tts(key, a.voice, s)
            start = t_cursor + pcm_sec(seg)
            cues += chunk_subtitles(s, start, pcm_sec(pcm))
            seg += pcm + silence(GAP)
        seg += silence(TAIL - GAP)
        dur = pcm_sec(seg)
        print(f"{sid}: 旁白 {dur:.1f}s（{len(sents)} 句）")

        # 畫面：outro 沿用最後一段的結尾畫面
        src = tl["07_ar_aging"] if sid == "_outro" else tl[sid]
        if sid == "_outro":
            start_t, raw_len = src["ready"] - 0.1, 0.1
        else:
            start_t, raw_len = src["start"], max(src["ready"] - src["start"], 0.5)
        vf = [f"fps=30", f"scale={W}:{H}"]
        if raw_len > dur:  # 太長：加速壓縮思考時間
            f = raw_len / dur
            if f > 2.2:
                print(f"  [警告] 加速 {f:.1f} 倍，畫面可能過快")
            vf.append(f"setpts=PTS/{f:.4f}")
        else:  # 太短：結果畫面停住等旁白
            vf.append(f"tpad=stop_mode=clone:stop_duration={dur - raw_len + 0.2:.3f}")
        sf = WORK / f"scene_{idx}.mp4"
        run(["ffmpeg", "-loglevel", "error", "-y", "-ss", f"{start_t:.2f}", "-t", f"{raw_len:.2f}",
             "-i", str(raw), "-vf", ",".join(vf), "-t", f"{dur:.3f}", "-an",
             "-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p", str(sf)])
        scene_files.append(sf)
        audio += seg
        subs += cues
        t_cursor += dur

    # 串接畫面
    lst = WORK / "scenes.txt"
    lst.write_text("".join(f"file '{p}'\n" for p in scene_files), encoding="utf-8")
    silent = WORK / "video_silent.mp4"
    run(["ffmpeg", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(silent)])

    # 旁白音軌
    wav = WORK / "narration.wav"
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes(audio)

    # 字幕：SRT + PNG 疊圖
    (REC / "llm_erp_demo.srt").write_text(
        "".join(f"{i}\n{srt_time(s)} --> {srt_time(e)}\n{c}\n\n" for i, (s, e, c) in enumerate(subs, 1)),
        encoding="utf-8")
    font = pick_font(32)
    bar = WORK / "bar.png"
    bar_png(bar)
    inputs, graph, last = ["-i", str(silent), "-i", str(bar)], [], "[0:v]"
    graph.append(f"{last}[1:v]overlay=x=0:y=H-h[vb]")
    last = "[vb]"
    for i, (s, e, c) in enumerate(subs, 1):
        png = WORK / f"sub_{i:03d}.png"
        w, h = subtitle_png(c, font, png)
        inputs += ["-i", str(png)]
        out = f"[v{i}]"
        graph.append(f"{last}[{i + 1}:v]overlay=x=(W-w)/2:y=H-{BAR_H}+({BAR_H}-h)/2:enable='between(t,{s:.3f},{e:.3f})'{out}")
        last = out
    gs = WORK / "filter.txt"
    gs.write_text(";".join(graph), encoding="utf-8")
    run(["ffmpeg", "-loglevel", "error", "-y", *inputs, "-i", str(wav), "-/filter_complex", str(gs),
         "-map", last, "-map", f"{len(subs) + 2}:a", "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
         "-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
         "-movflags", "+faststart", "-shortest", a.out])
    print(f"\n完成：{a.out}（{t_cursor:.0f} 秒）\n字幕：{REC / 'llm_erp_demo.srt'}")


if __name__ == "__main__":
    main()

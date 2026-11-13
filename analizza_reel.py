"""Analizza reel virali (Instagram / TikTok / Shorts) GRATIS su GitHub Actions, in TESTO.

Per ogni link scrive analisi/<id>/report.md con:
  - dati: autore, views, like, commenti, data, caption, durata
  - tagli di scena con i secondi (ritmo del montaggio)
  - testo a schermo per scena (OCR tesseract, ita+eng)
  - parlato trascritto con i secondi (faster-whisper)
  - audio: momento del "drop" (salto di volume più forte)
e una sola miniatura piccola analisi/<id>/scene.jpg (1 fotogramma per scena), da guardare solo se serve.
Il video non viene salvato nel repo.

Uso: python analizza_reel.py URL [URL ...]      oppure senza argomenti legge analisi/link.txt
"""
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

BASE = Path(__file__).resolve().parent
OUT = BASE / "analisi"


def sh(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def id_da_url(url):
    m = re.search(r"/(?:reel|reels|p|video|shorts)/([A-Za-z0-9_-]+)", url)
    return m.group(1) if m else re.sub(r"\W+", "_", url)[-20:]


def scarica(url, cart):
    r = sh(["yt-dlp", "-q", "--no-warnings", "-f", "mp4/best", "--write-info-json",
            "-o", str(cart / "v.%(ext)s"), url])
    video = next(iter(sorted(cart.glob("v.mp4")) or sorted(cart.glob("v.*[!n]"))), None)
    if not video:
        raise RuntimeError(f"download fallito: {r.stderr.strip()[-300:]}")
    info = {}
    j = cart / "v.info.json"
    if j.exists():
        info = json.loads(j.read_text())
    return video, info


def durata(video):
    return float(sh(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                     str(video)]).stdout.strip() or 0)


def tagli(video, soglia=0.3):
    err = sh(["ffmpeg", "-nostdin", "-i", str(video), "-vf", f"select='gt(scene,{soglia})',showinfo",
              "-f", "null", "-"]).stderr
    t = [round(float(x), 2) for x in re.findall(r"pts_time:([0-9.]+)", err)]
    out = []
    for x in t:  # unisci tagli a meno di 0.3s
        if not out or x - out[-1] > 0.3:
            out.append(x)
    return out


def frame(video, t, dest, larg=480):
    sh(["ffmpeg", "-nostdin", "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", str(video),
        "-frames:v", "1", "-vf", f"scale={larg}:-1", str(dest)])
    return dest.exists()


def ocr(img):
    r = sh(["tesseract", str(img), "-", "-l", "ita+eng", "--psm", "11"])
    righe = [l.strip() for l in r.stdout.splitlines()]
    # tieni solo righe "da testo a schermo": almeno 2 lettere di fila, niente rumore
    buone = [l for l in righe if re.search(r"[A-Za-zÀ-ÿ]{2,}", l) and len(l) >= 3]
    return " / ".join(buone)


def trascrivi(video):
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        return None
    import numpy as np
    # audio decodificato con ffmpeg (16 kHz mono float32): evita il decoder PyAV di faster-whisper
    pcm = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(video), "-ac", "1", "-ar", "16000",
                          "-f", "f32le", "-"], capture_output=True).stdout
    audio = np.frombuffer(pcm, dtype=np.float32)
    if audio.size < 16000:
        return "-", []
    m = WhisperModel("small", compute_type="int8")
    seg, info = m.transcribe(audio, vad_filter=True)
    righe = [f"{s.start:.1f}-{s.end:.1f}s  {s.text.strip()}" for s in seg]
    return info.language, righe


def drop(video):
    """Secondo in cui il volume (loudness momentanea) sale di più rispetto al secondo prima."""
    err = sh(["ffmpeg", "-nostdin", "-i", str(video), "-af", "ebur128=metadata=1,ametadata=print:key=lavfi.r128.M",
              "-f", "null", "-"]).stderr
    t = [float(x) for x in re.findall(r"pts_time:([0-9.]+)", err)]
    m = [max(float(x), -45.0) for x in re.findall(r"lavfi\.r128\.M=(-?[0-9.]+|-inf)", err.replace("-inf", "-120"))]  # sotto -45 = silenzio
    if len(t) < 20 or len(m) != len(t):
        return None
    passo = max(1, int(len(t) / max(t[-1], 1)))  # campioni al secondo
    best, bt = 0, None
    for i in range(passo, len(m)):
        d = m[i] - m[i - passo]
        if t[i] >= 1.5 and d > best:   # i primi 1,5s sono l'attacco dell'audio, non un drop
            best, bt = d, t[i]
    return (round(bt, 1), round(best, 1)) if bt else None


def analizza(url):
    rid = id_da_url(url)
    dest = OUT / rid
    dest.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        video, info = scarica(url, tmp)
        dur = durata(video)
        cuts = tagli(video)
        inizi = [0.0] + cuts
        scene = []
        for i, a in enumerate(inizi):
            b = inizi[i + 1] if i + 1 < len(inizi) else dur
            mid = a + min((b - a) / 2, 1.0)
            img = tmp / f"s{i:02d}.png"
            testo = ocr(img) if frame(video, mid, img, 720) else ""
            frame(video, mid, tmp / f"t{i:02d}.png", 120)
            scene.append((a, b, testo))
        # miniatura: 1 fotogramma per scena, piccolo (max 16 scene)
        mini = sorted(tmp.glob("t*.png"))[:16]
        if mini:
            col = min(len(mini), 8)
            sh(["ffmpeg", "-nostdin", "-v", "error", "-y", "-framerate", "1", "-i", str(tmp / "t%02d.png"),
                "-vf", f"tile={col}x{(len(mini) + col - 1) // col}", "-frames:v", "1", str(dest / "scene.jpg")])
        try:
            tr = trascrivi(video)
        except Exception as e:  # noqa: BLE001  la trascrizione non deve bloccare il report
            print(f"   trascrizione non riuscita: {e}")
            tr = None
        dr = drop(video)

    def n(k):
        v = info.get(k)
        return f"{v:,}".replace(",", ".") if isinstance(v, int) else "-"

    righe = [f"# Reel {rid}", f"- link: {url}",
             f"- autore: {info.get('uploader') or info.get('channel') or '-'}  ·  data: {info.get('upload_date', '-')}",
             f"- views: {n('view_count')}  ·  like: {n('like_count')}  ·  commenti: {n('comment_count')}",
             f"- durata: {dur:.1f}s  ·  scene: {len(scene)}  ·  durata media scena: {dur / max(len(scene), 1):.1f}s",
             f"- audio: {info.get('track') or '-'} — {info.get('artist') or ''}".rstrip(" —"),
             f"- drop audio (salto di volume più forte): {f'{dr[0]}s (+{dr[1]} LU)' if dr else 'non rilevato'}",
             "", "## Caption", (info.get("description") or "-").strip()[:600], "",
             "## Scene (tagli + testo a schermo letto con OCR)", "| # | da | a | testo a schermo |", "|---|---|---|---|"]
    for i, (a, b, t) in enumerate(scene, 1):
        righe.append(f"| {i} | {a:.1f}s | {b:.1f}s | {t.replace('|', '/')[:160] or '-'} |")
    righe += ["", "## Parlato"]
    if tr is None:
        righe.append("trascrizione non disponibile")
    elif not tr[1]:
        righe.append(f"nessun parlato (solo musica/suoni) — lingua rilevata: {tr[0]}")
    else:
        righe += [f"lingua: {tr[0]}", *tr[1]]
    (dest / "report.md").write_text("\n".join(righe) + "\n", encoding="utf-8")
    print(f"✅ {rid}: {len(scene)} scene, {dur:.1f}s → analisi/{rid}/report.md")
    return rid


def main():
    urls = sys.argv[1:]
    if not urls:
        f = OUT / "link.txt"
        urls = [l.strip() for l in f.read_text().splitlines() if l.strip().startswith("http")] if f.exists() else []
    urls = [u for x in urls for u in x.split()]
    if not urls:
        sys.exit("nessun link: passali come argomenti o mettili in analisi/link.txt")
    ok = []
    for u in urls:
        try:
            ok.append(analizza(u))
        except Exception as e:  # noqa: BLE001
            print(f"❌ {u}: {e}")
    indice = OUT / "INDICE.md"
    vecchio = indice.read_text() if indice.exists() else "# Reel analizzati\n"
    for rid in ok:
        r = (OUT / rid / "report.md").read_text().splitlines()
        riga = f"- [{rid}]({rid}/report.md) — " + " · ".join(x[2:] for x in r[2:4])
        if rid not in vecchio:
            vecchio += riga + "\n"
    indice.write_text(vecchio)


if __name__ == "__main__":
    main()

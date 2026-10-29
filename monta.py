#!/usr/bin/env python3
"""Monta i reel di una pagina da clip_originali/<pagina>/ seguendo pagine/<pagina>/ricette.yaml.

Uso:  python monta.py lucedifede            (monta tutti i reel)
      python monta.py lucedifede lf03 lf07  (solo quelli il cui nome inizia così)

Ricetta (in ricette.yaml):
  - nome: lf01_cade_scaletta
    testo: "Hook in alto per tutto il video 😭"      # bianco grassetto con bordo nero, senza banda
    posizione: alto                                  # alto | centro | basso (metterlo sopra le parti sgranate)
    cta: "Commenta AMEN se la vuoi 🙏"                # opzionale, ultimi cta_secondi, sotto l'hook
    pezzi:                                           # clip  inizio  fine  [velocità]
      - h1_lei_cade_scaletta 0 4.06
      - s2_buio_accensione 1.2 3.04 1.0
Esce in clip_montate/<pagina>/<nome>.mp4, 1080x1920 30fps, senza audio (l'audio lo mette `metti-audio`).
"""
import re
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path

import yaml
from PIL import Image, ImageDraw, ImageFont

BASE = Path(__file__).resolve().parent
W, H, FPS = 1080, 1920, 30
FONT_TESTO = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
FONT_EMOJI = "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf"  # bitmap a 109 px
Y_POS = {"alto": 0.115, "centro": 0.42, "basso": 0.70}


# ------------------------------------------------------------------ testo con emoji a colori
def _e_emoji(ch):
    o = ord(ch)
    return (o >= 0x1F000 or 0x2600 <= o <= 0x27BF or 0x2B00 <= o <= 0x2BFF or o in (0x200D, 0xFE0F)
            or unicodedata.category(ch) == "So")


def _gruppi(riga):
    """Spezza una riga in [(testo, False), (emoji, True), ...] tenendo insieme ZWJ/selettori."""
    out = []
    for ch in riga:
        em = _e_emoji(ch)
        if out and (out[-1][1] == em or ch in "‍️"):
            out[-1][0] += ch
        else:
            out.append([ch, em])
    return out


def _cluster_emoji(s):
    """Divide una sequenza di emoji in singoli glifi (unisce ZWJ e variation selector)."""
    gl = []
    for ch in s:
        if gl and (ch in "‍️" or gl[-1].endswith("‍")):
            gl[-1] += ch
        else:
            gl.append(ch)
    return gl


class Scrittore:
    def __init__(self, px):
        self.px = px
        self.f = ImageFont.truetype(FONT_TESTO, px)
        self.fe = ImageFont.truetype(FONT_EMOJI, 109)
        self.bordo = max(4, px // 11)
        self.em_px = int(px * 1.12)

    def _emoji_img(self, g):
        im = Image.new("RGBA", (160, 160), (0, 0, 0, 0))
        ImageDraw.Draw(im).text((0, 0), g, font=self.fe, embedded_color=True)
        bb = im.getbbox() or (0, 0, 1, 1)
        im = im.crop(bb)
        r = self.em_px / max(im.size)
        return im.resize((max(1, int(im.width * r)), max(1, int(im.height * r))), Image.LANCZOS)

    def larghezza(self, riga):
        w = 0
        for t, em in _gruppi(riga):
            if em:
                w += sum(self._emoji_img(g).width + 4 for g in _cluster_emoji(t))
            else:
                w += self.f.getlength(t)
        return w

    def a_capo(self, testo, max_w):
        righe = []
        for par in testo.split("\n"):
            cur = ""
            for parola in par.split(" "):
                prova = (cur + " " + parola).strip()
                if cur and self.larghezza(prova) > max_w:
                    righe.append(cur)
                    cur = parola
                else:
                    cur = prova
            righe.append(cur)
        return righe

    def disegna(self, img, testo, y_top, max_w=W - 120):
        d = ImageDraw.Draw(img)
        alt = int(self.px * 1.22)
        for i, riga in enumerate(self.a_capo(testo, max_w)):
            x = (W - self.larghezza(riga)) / 2
            y = y_top + i * alt
            for t, em in _gruppi(riga):
                if em:
                    for g in _cluster_emoji(t):
                        e = self._emoji_img(g)
                        img.alpha_composite(e, (int(x), int(y + (self.px - e.height) / 2 + self.px * 0.08)))
                        x += e.width + 4
                else:
                    d.text((x, y), t, font=self.f, fill="white", stroke_width=self.bordo, stroke_fill="black")
                    x += self.f.getlength(t)
        return y_top + len(self.a_capo(testo, max_w)) * alt


def png_testo(testo, posizione, dest, cta=None, px=66):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    s = Scrittore(px)
    y = int(H * Y_POS.get(posizione, Y_POS["alto"]))
    fine = s.disegna(img, testo, y) if testo else y
    if cta:
        Scrittore(int(px * 0.9)).disegna(img, cta, fine + int(px * 0.5))
    img.save(dest)


# ------------------------------------------------------------------ montaggio
def _pezzo(riga):
    p = str(riga).split()
    return p[0], float(p[1]), float(p[2]), float(p[3]) if len(p) > 3 else 1.0


def monta(pagina, r, tmp):
    src_dir = BASE / "clip_originali" / pagina
    out_dir = BASE / "clip_montate" / pagina
    out_dir.mkdir(parents=True, exist_ok=True)
    pezzi = [_pezzo(p) for p in r["pezzi"]]
    durata = sum((b - a) / v for _, a, b, v in pezzi)
    cta_s = float(r.get("cta_secondi", 2.5))
    pos = r.get("posizione", "alto")

    args, fc = ["ffmpeg", "-nostdin", "-v", "error", "-y"], []
    for i, (clip, a, b, v) in enumerate(pezzi):
        f = src_dir / f"{clip}.mp4"
        if not f.exists():
            sys.exit(f"clip mancante: {f}")
        args += ["-ss", f"{a:.3f}", "-t", f"{b - a:.3f}", "-i", str(f)]
        fc.append(f"[{i}:v]setpts=(PTS-STARTPTS)/{v},scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,"
                  f"crop={W}:{H},setsar=1,fps={FPS}[v{i}]")
    n = len(pezzi)
    fc.append("".join(f"[v{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0[base]")

    # testo: solo hook fino all'ultima parte, poi hook + CTA
    ultimo = "base"
    k = n
    finestre = []
    if r.get("cta"):
        t_cta = max(durata - cta_s, 0)
        finestre = [(r.get("testo"), None, 0, t_cta), (r.get("testo"), r["cta"], t_cta, durata + 1)]
    elif r.get("testo"):
        finestre = [(r["testo"], None, 0, durata + 1)]
    for j, (testo, cta, t0, t1) in enumerate(finestre):
        png = Path(tmp) / f"{r['nome']}_{j}.png"
        png_testo(testo, pos, png, cta)
        args += ["-i", str(png)]
        fc.append(f"[{ultimo}][{k}:v]overlay=0:0:enable='between(t,{t0:.3f},{t1:.3f})'[o{j}]")
        ultimo, k = f"o{j}", k + 1

    dest = out_dir / f"{r['nome']}.mp4"
    args += ["-filter_complex", ";".join(fc), "-map", f"[{ultimo}]", "-an",
             "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
             "-movflags", "+faststart", str(dest)]
    subprocess.run(args, check=True)
    print(f"✓ {dest.relative_to(BASE)}  {durata:.1f}s  {n} pezzi")


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    pagina, filtri = sys.argv[1], sys.argv[2:]
    ricette = yaml.safe_load((BASE / "pagine" / pagina / "ricette.yaml").read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as tmp:
        for r in ricette["reel"]:
            if not filtri or any(r["nome"].startswith(f) for f in filtri):
                monta(pagina, r, tmp)


if __name__ == "__main__":
    main()

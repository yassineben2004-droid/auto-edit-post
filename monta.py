#!/usr/bin/env python3
"""Monta i reel di una pagina da clip_originali/<pagina>/ seguendo pagine/<pagina>/ricette.yaml.

Uso:  python monta.py lucedifede            (monta tutti i reel)
      python monta.py lucedifede lf03 lf07  (solo quelli il cui nome inizia così)

Ricetta (in ricette.yaml):
  - nome: lf01_cade_scaletta
    testo: "Hook in alto per tutto il video 😭"      # bianco grassetto con bordo nero, senza banda
    posizione: alto                                  # alto | centro | basso | 0.58 (metterlo sopra le parti sgranate)
    cta: "Commenta AMEN se la vuoi 🙏"                # opzionale, ultimi cta_secondi, sotto l'hook
    pezzi:                                           # clip  inizio  fine  [velocità]
      - h1_lei_cade_scaletta 0 4.06
      - s2_buio_accensione 1.2 3.04 1.0
    testi_scene: ["Hook", "Testo scena 2", ""]       # facoltativo: un testo per ogni pezzo (sostituisce testo/cta)
    stile: tiktok                                    # facoltativo: tiktok | tiktok_regular | classico (se manca: rotazione 60/40)
    copri_sgranature: false                          # facoltativo: NON spostare il testo sulle parti sgranate
Esce in clip_montate/<pagina>/<nome>.mp4, 1080x1920 30fps, senza audio (l'audio lo mette `metti-audio`).

Testo "tiktok": font TikTok Sans SemiBold (quello del testo nativo dell'app, open source OFL, in fonts/),
bianco con bordino scuro sottile e ombra morbida. Emoji iOS: si usano solo se c'è il font Apple Color Emoji,
cioè quando si monta su un Mac (workflow GitHub "Monta reel" su runner macOS). Su Linux ripiega sulle emoji
Google e lo scrive; con EMOJI_IOS=obbligatorie invece si ferma.

PARTI SGRANATE: se in clip_originali/<pagina>/sgranature.yaml c'è una parte sgranata (o scritta/emoji residua)
di una clip usata nel reel, il testo viene messo SOPRA quella parte (centrato sulla sua altezza), qualunque sia
`posizione`. Se la parte è segnata `forte: true` (si vede molto) il testo esce EVIDENZIATO: riquadro bianco
arrotondato con scritta nera, largo almeno quanto la parte da coprire. Formato in sgranature.yaml; per trovarle
python controlla_clip.py <pagina> crea i fogli con i fotogrammi e la griglia delle altezze.

Uso extra:  python monta.py <pagina> --solo-nuovi   (monta solo i reel che non esistono ancora in clip_montate)
"""
import os
import re
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path

import yaml
from PIL import Image, ImageDraw, ImageFilter, ImageFont

BASE = Path(__file__).resolve().parent
W, H, FPS = 1080, 1920, 30
FFMPEG = os.environ.get("FFMPEG", "ffmpeg")
FONT_TIKTOK = {"tiktok": BASE / "fonts" / "TikTokSans-SemiBold.ttf",          # predefinito (~60%)
               "tiktok_regular": BASE / "fonts" / "TikTokSans-Regular.ttf"}   # test non grassetto (~40%)
# Rotazione stili per i reel con testo che non scelgono `stile`: su ogni 10, 4 in regular (posizioni 1, 3, 6, 8)
ROTAZIONE_REGULAR = {1, 3, 6, 8}
# font "classico": Liberation su Linux, Arial Bold su Mac, altrimenti TikTok Sans Bold del repo
FONT_CLASSICO = next((f for f in ["/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
                                  "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
                                  "/Library/Fonts/Arial Bold.ttf"] if os.path.exists(f)),
                     str(BASE / "fonts" / "TikTokSans-Bold.ttf"))
EMOJI_APPLE = ["/System/Library/Fonts/Apple Color Emoji.ttc"]
EMOJI_GOOGLE = ["/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",
                "/usr/share/fonts/noto/NotoColorEmoji.ttf"]
Y_POS = {"alto": 0.115, "centro": 0.42, "basso": 0.70}


def _font_emoji():
    """(font, nome) per le emoji: Apple (iOS) se c'è, altrimenti Google. Le bitmap hanno taglie fisse."""
    for p in EMOJI_APPLE:
        if Path(p).exists():
            for size in (160, 96, 64):
                try:
                    return ImageFont.truetype(p, size), "ios"
                except OSError:
                    pass
    if os.environ.get("EMOJI_IOS") == "obbligatorie":
        sys.exit("Emoji iOS richieste ma il font Apple Color Emoji non c'è: monta su macOS (workflow 'Monta reel').")
    for p in EMOJI_GOOGLE:
        if Path(p).exists():
            print("⚠ emoji Google (non iOS): per le emoji iOS monta con il workflow 'Monta reel' su macOS")
            return ImageFont.truetype(p, 109), "google"
    sys.exit("nessun font emoji trovato")


_EMOJI = None


def font_emoji():
    global _EMOJI
    if _EMOJI is None:
        _EMOJI = _font_emoji()
    return _EMOJI


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
    def __init__(self, px, stile="tiktok"):
        self.px = px
        self.stile = stile
        if stile in FONT_TIKTOK:
            self.f = ImageFont.truetype(str(FONT_TIKTOK[stile]), px)
            self.bordo = max(2, px // 26)          # bordino sottile come il testo nativo
            self.interlinea = 1.10
        else:
            self.f = ImageFont.truetype(FONT_CLASSICO, px)
            self.bordo = max(4, px // 11)
            self.interlinea = 1.22
        self.fe = font_emoji()[0]
        self.em_px = int(px * (1.05 if stile in FONT_TIKTOK else 1.12))

    def _emoji_img(self, g):
        im = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
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
            parole = []
            for parola in par.split(" "):
                # un'emoji da sola non va mai a capo: resta attaccata alla parola prima
                if parole and parola and all(em for _, em in _gruppi(parola)):
                    parole[-1] += " " + parola
                else:
                    parole.append(parola)
            for parola in parole:
                prova = (cur + " " + parola).strip()
                if cur and self.larghezza(prova) > max_w:
                    righe.append(cur)
                    cur = parola
                else:
                    cur = prova
            righe.append(cur)
        return righe

    def altezza(self, testo, max_w=W - 120):
        return len(self.a_capo(testo, max_w)) * int(self.px * self.interlinea)

    def disegna(self, img, testo, y_top, max_w=W - 120, evidenziato=False, min_w=0, min_h=0):
        """evidenziato: riquadro bianco arrotondato dietro al testo (scritta nera), per coprire le parti sgranate.
        min_w / min_h: il riquadro è largo/alto almeno così (px), per coprire tutta la parte sgranata."""
        alt = int(self.px * self.interlinea)
        testo_lay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ombra = Image.new("RGBA", img.size, (0, 0, 0, 0))
        d, do = ImageDraw.Draw(testo_lay), ImageDraw.Draw(ombra)
        emoji = []
        righe = self.a_capo(testo, max_w)
        if evidenziato:
            pad_x, pad_y = int(self.px * 0.38), int(self.px * 0.20)
            bw = min(W - 40, max(max(self.larghezza(r) for r in righe) + 2 * pad_x, min_w))
            bh = max(len(righe) * alt + 2 * pad_y, min_h)
            extra = (bh - len(righe) * alt - 2 * pad_y) / 2          # se il riquadro è più alto del testo
            x0, y0 = (W - bw) / 2, y_top - pad_y - extra
            fondo = Image.new("RGBA", img.size, (0, 0, 0, 0))
            df = ImageDraw.Draw(fondo)
            df.rounded_rectangle([x0, y0 + 6, x0 + bw, y0 + bh + 6], radius=int(self.px * 0.32), fill=(0, 0, 0, 70))
            img.alpha_composite(fondo.filter(ImageFilter.GaussianBlur(8)))
            ImageDraw.Draw(img).rounded_rectangle([x0, y0, x0 + bw, y0 + bh], radius=int(self.px * 0.32),
                                                  fill=(255, 255, 255, 255))
        for i, riga in enumerate(righe):
            x = (W - self.larghezza(riga)) / 2
            y = y_top + i * alt
            for t, em in _gruppi(riga):
                if evidenziato and not em:
                    d.text((x, y), t, font=self.f, fill=(0, 0, 0, 255))
                    x += self.f.getlength(t)
                elif em:
                    for g in _cluster_emoji(t):
                        e = self._emoji_img(g)
                        emoji.append((e, (int(x), int(y + (self.px - e.height) / 2 + self.px * 0.10))))
                        x += e.width + 4
                elif self.stile in FONT_TIKTOK:
                    # ombra morbida sotto + bordino scuro sottile, come il testo "Classic" di TikTok
                    do.text((x, y), t, font=self.f, fill=(0, 0, 0, 150),
                            stroke_width=self.bordo + 2, stroke_fill=(0, 0, 0, 150))
                    d.text((x, y), t, font=self.f, fill="white", stroke_width=self.bordo, stroke_fill=(0, 0, 0, 215))
                    x += self.f.getlength(t)
                else:
                    d.text((x, y), t, font=self.f, fill="white", stroke_width=self.bordo, stroke_fill="black")
                    x += self.f.getlength(t)
        if self.stile in FONT_TIKTOK and not evidenziato:
            img.alpha_composite(ombra.filter(ImageFilter.GaussianBlur(self.px / 28)))
        img.alpha_composite(testo_lay)
        for e, pos in emoji:
            img.alpha_composite(e, pos)
        return y_top + len(righe) * alt


def png_testo(testo, posizione, dest, cta=None, px=None, stile="tiktok", copri=None):
    """copri = parte sgranata da coprire (dict di sgranature.yaml): il testo si centra sulla sua altezza,
    evidenziato se è `forte`."""
    if px is None:
        px = 72 if stile in FONT_TIKTOK else 66
    max_w = W - 110 if stile in FONT_TIKTOK else W - 120
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    s = Scrittore(px, stile)
    try:
        frac = float(posizione)            # posizione anche come numero: 0.58 = 58% dall'alto
    except (TypeError, ValueError):
        frac = Y_POS.get(posizione, Y_POS["alto"])
    y = int(H * frac)
    evid, min_w, min_h = False, 0, 0
    if copri and testo:
        evid = bool(copri.get("forte"))
        min_w = int(W * float(copri.get("larghezza", 0)) + px * 0.4) if evid else 0
        min_h = int(H * float(copri.get("altezza", 0.05)) + px * 0.3) if evid else 0
        alt_riga = int(px * s.interlinea)
        if evid or H * float(copri.get("altezza", 0.05)) > alt_riga * 1.3:
            y = int(H * float(copri["y"]) - s.altezza(testo, max_w) / 2)     # parte grande: centro del blocco
        else:
            # parte sottile (emoji/scritta residua): la copre la PRIMA riga, mai lo spazio tra due righe
            y = int(H * float(copri["y"]) - px * 0.62)
        y = max(int(H * 0.06), min(y, int(H * 0.86) - s.altezza(testo, max_w)))
    fine = s.disegna(img, testo, y, max_w, evidenziato=evid, min_w=min_w, min_h=min_h) if testo else y
    if cta:
        Scrittore(int(px * 0.9), stile).disegna(img, cta, fine + int(px * (0.8 if evid else 0.5)), max_w,
                                                evidenziato=evid)
    img.save(dest)


# ------------------------------------------------------------------ parti sgranate
def carica_sgranature(pagina):
    p = BASE / "clip_originali" / pagina / "sgranature.yaml"
    return (yaml.safe_load(p.read_text(encoding="utf-8")) or {}) if p.exists() else {}


def sgranatura_da_coprire(pezzi, sgr, t0, t1):
    """La parte sgranata più importante visibile tra t0 e t1 (secondi del reel montato), o None.
    Conta quanto tempo resta a schermo; quelle `forte` valgono il triplo."""
    meglio, punti, t = None, 0.0, 0.0
    for clip, a, b, v in pezzi:
        dur = (b - a) / v
        s0, s1 = max(t, t0), min(t + dur, t1)            # parte di questo pezzo dentro la finestra del testo
        if s1 > s0:
            c0, c1 = a + (s0 - t) * v, a + (s1 - t) * v  # stessi istanti, in secondi della clip
            for dif in sgr.get(clip) or []:
                da, fino = float(dif.get("da", 0)), float(dif.get("a", 1e9))
                vis = max(0.0, min(c1, fino) - max(c0, da)) / v
                pt = vis * (3 if dif.get("forte") else 1)
                if vis > 0.3 and pt > punti:
                    meglio, punti = dif, pt
        t += dur
    return meglio


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
    sgr = carica_sgranature(pagina) if r.get("copri_sgranature", True) else {}

    args, fc = [FFMPEG, "-nostdin", "-v", "error", "-y"], []
    for i, (clip, a, b, v) in enumerate(pezzi):
        f = src_dir / f"{clip}.mp4"
        if not f.exists():
            sys.exit(f"clip mancante: {f}")
        args += ["-ss", f"{a:.3f}", "-t", f"{b - a:.3f}", "-i", str(f)]
        fc.append(f"[{i}:v]setpts=(PTS-STARTPTS)/{v},scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,"
                  f"crop={W}:{H},setsar=1,fps={FPS}[v{i}]")
    n = len(pezzi)
    fc.append("".join(f"[v{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0[base]")

    # testo: solo hook fino all'ultima parte, poi hook + CTA.
    # Con cta_posizione la CTA SOSTITUISCE l'hook (come nei virali) e va a quell'altezza.
    ultimo = "base"
    k = n
    finestre = []
    cta_pos = r.get("cta_posizione")
    if r.get("cta"):
        t_cta = max(durata - cta_s, 0)
        if cta_pos is not None:
            finestre = [(r.get("testo"), None, pos, 0, t_cta), (r["cta"], None, cta_pos, t_cta, durata + 1)]
        else:
            finestre = [(r.get("testo"), None, pos, 0, t_cta), (r.get("testo"), r["cta"], pos, t_cta, durata + 1)]
    elif r.get("testo"):
        finestre = [(r["testo"], None, pos, 0, durata + 1)]
    if r.get("testi_scene"):
        # un testo diverso per ogni pezzo (come nei virali che cambiano scritta a ogni scena);
        # "" = nessun testo su quel pezzo, pezzi consecutivi con lo stesso testo restano un'unica scritta
        finestre, t = [], 0.0
        for (_, a, b, v), testo in zip(pezzi, r["testi_scene"]):
            t1 = t + (b - a) / v
            if testo and finestre and finestre[-1][0] == testo:
                finestre[-1] = (testo, None, pos, finestre[-1][3], t1)
            elif testo:
                finestre.append((testo, None, pos, t, t1))
            t = t1
        if finestre:
            finestre[-1] = finestre[-1][:4] + (durata + 1,)
    coperte = []
    for j, (testo, cta, posiz, t0, t1) in enumerate(finestre):
        png = Path(tmp) / f"{r['nome']}_{j}.png"
        dif = sgranatura_da_coprire(pezzi, sgr, t0, min(t1, durata))
        if dif and not testo and cta:                    # finestra con sola CTA: la CTA fa da copertura
            testo, cta = cta, None
        png_testo(testo, posiz, png, cta, stile=r["stile"], copri=dif if testo else None)
        if dif and testo:
            coperte.append(f"y={dif['y']}{' EVIDENZIATO' if dif.get('forte') else ''}")
            r["_evidenziato"] = r.get("_evidenziato") or bool(dif.get("forte"))
        args += ["-i", str(png)]
        fc.append(f"[{ultimo}][{k}:v]overlay=0:0:enable='between(t,{t0:.3f},{t1:.3f})'[o{j}]")
        ultimo, k = f"o{j}", k + 1

    dest = out_dir / f"{r['nome']}.mp4"
    args += ["-filter_complex", ";".join(fc), "-map", f"[{ultimo}]", "-an",
             "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
             "-movflags", "+faststart", str(dest)]
    subprocess.run(args, check=True)
    print(f"✓ {dest.relative_to(BASE)}  {durata:.1f}s  {n} pezzi"
          + (f"  · testo sulle parti sgranate: {', '.join(coperte)}" if coperte else ""))
    if sgr and not finestre and any(sgr.get(c) for c, *_ in pezzi):
        print(f"  ⚠ {r['nome']}: la clip ha parti sgranate ma il reel non ha testo per coprirle")


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    pagina = sys.argv[1]
    solo_nuovi = "--solo-nuovi" in sys.argv[2:]
    filtri = [a for a in sys.argv[2:] if not a.startswith("--")]
    ricette = yaml.safe_load((BASE / "pagine" / pagina / "ricette.yaml").read_text(encoding="utf-8"))
    assegna_stili(ricette["reel"])
    with tempfile.TemporaryDirectory() as tmp:
        for r in ricette["reel"]:
            if filtri and not any(r["nome"].startswith(f) for f in filtri):
                continue
            if solo_nuovi and (BASE / "clip_montate" / pagina / f"{r['nome']}.mp4").exists():
                continue
            monta(pagina, r, tmp)
            registra_stile(pagina, r)


def assegna_stili(reel):
    """Stile a rotazione per i reel con testo senza `stile` esplicito: 60% tiktok (semibold), 40% tiktok_regular.
    Dipende solo dall'ordine nella ricetta, quindi rimontando lo stesso reel lo stile non cambia."""
    i = 0
    for r in reel:
        if not (r.get("testo") or r.get("cta")):
            r.setdefault("stile", "tiktok")
            continue
        if "stile" not in r:
            r["stile"] = "tiktok_regular" if i % 10 in ROTAZIONE_REGULAR else "tiktok"
        i += 1


def registra_stile(pagina, r):
    """clip_montate/<pagina>/stili.csv: nome reel → stile del testo (per confrontare gli insights)."""
    p = BASE / "clip_montate" / pagina / "stili.csv"
    righe = dict(l.split(",", 1) for l in p.read_text(encoding="utf-8").splitlines()[1:] if "," in l) if p.exists() else {}
    righe[r["nome"]] = ("clean" if not (r.get("testo") or r.get("cta") or r.get("testi_scene"))
                        else r["stile"] + ("+evidenziato" if r.get("_evidenziato") else ""))
    p.write_text("reel,stile\n" + "".join(f"{k},{v}\n" for k, v in sorted(righe.items())), encoding="utf-8")


if __name__ == "__main__":
    main()

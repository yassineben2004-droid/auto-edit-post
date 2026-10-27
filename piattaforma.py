#!/usr/bin/env python3
"""
Auto Edit & Post — piattaforma di pubblicazione multi-pagina (Instagram Reels + audio di tendenza).

Struttura:
  piattaforma.yaml                 impostazioni generali
  pagine/<pagina>/pagina.yaml      account, ORARI FISSI, hashtag, regole audio
  pagine/<pagina>/coda/            video in attesa + coda.csv (ordine di uscita, caption)
  pagine/<pagina>/stato.json       storico: turni pubblicati / mancati / coda vuota, audio usati, errori
  PANNELLO.md                      riepilogo di tutte le pagine (si aggiorna a ogni esecuzione)

A ogni orario di una pagina ("turno") esce il PRIMO video della sua coda.

Comandi:
  python piattaforma.py esegui [--prova]       pubblica i turni arrivati (lo lancia GitHub o il server)
  python piattaforma.py pannello               stato di tutte le pagine
  python piattaforma.py subito <pagina>        pubblica ADESSO il prossimo video della coda
  python piattaforma.py nuova <pagina> "Nome"  crea una nuova pagina
  python piattaforma.py aggiungi <pagina> <cartella video>... [--testi testi.txt] [--ricerca-audio natale]
  python piattaforma.py cron                   rigenera gli orari di GitHub Actions dagli orari delle pagine
  python piattaforma.py verifica               controlla token, account e quota di ogni pagina
  python piattaforma.py audio <pagina> [parole...]   elenca gli audio disponibili
"""
import argparse, csv, json, os, random, re, subprocess, sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

import lib_meta
from lib_meta import ErroreAPI, Meta, descrivi_audio, scegli_audio

BASE = Path(__file__).parent
PAGINE = BASE / "pagine"
GIORNI = ["lunedi", "martedi", "mercoledi", "giovedi", "venerdi", "sabato", "domenica"]
CAMPI_CODA = ["id", "file", "durata", "caption", "ricerca_audio", "audio_id", "origine", "aggiunto", "audio_file"]


# ================================================================ config / file
def cfg_generale():
    p = BASE / "piattaforma.yaml"
    c = yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else {}
    c.setdefault("api_version", "v22.0")
    c.setdefault("fuso_orario", "Europe/Rome")
    c.setdefault("finestra_minuti", 90)   # un turno si può ancora pubblicare fino a N minuti dopo l'orario
    c.setdefault("max_per_esecuzione", 1)  # post al massimo per pagina a ogni esecuzione (mai due Reel attaccati)
    return c


def elenco_pagine():
    return sorted(p.name for p in PAGINE.iterdir() if (p / "pagina.yaml").exists()) if PAGINE.exists() else []


def cfg_pagina(nome):
    c = yaml.safe_load((PAGINE / nome / "pagina.yaml").read_text(encoding="utf-8"))
    c.setdefault("nome", nome)
    c.setdefault("attiva", True)
    c.setdefault("token_env", "TOKEN_META")
    c.setdefault("orari", {})
    c.setdefault("audio", {})
    return c


def leggi_coda(nome):
    p = PAGINE / nome / "coda" / "coda.csv"
    if not p.exists():
        return []
    with open(p, encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def scrivi_coda(nome, righe):
    p = PAGINE / nome / "coda" / "coda.csv"
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=CAMPI_CODA, extrasaction="ignore")
        w.writeheader()
        w.writerows(righe)


def leggi_stato(nome):
    p = PAGINE / nome / "stato.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {"dal": None, "turni": {}, "usati": [], "scartati": {}, "errori": {}, "audio_usati": []}


def scrivi_stato(nome, st):
    (PAGINE / nome / "stato.json").write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")


def token_per(pag):
    """Token dalla variabile indicata, oppure dal pacchetto di secret di GitHub (SEGRETI)."""
    t = os.environ.get(pag["token_env"])
    if t:
        return t
    try:
        return json.loads(os.environ.get("SEGRETI", "{}")).get(pag["token_env"], "")
    except ValueError:
        return ""


# ================================================================ orari / turni
def orari_del_giorno(pag, giorno: date):
    o = pag.get("orari") or {}
    nome = GIORNI[giorno.weekday()]
    # priorità: data precisa ("2026-10-27") > giorno della settimana > ogni_giorno
    lista = o.get(giorno.isoformat(), o.get(nome, o.get("ogni_giorno", [])))
    return sorted({str(x) for x in lista})


def turni_tra(pag, da: datetime, a: datetime, tz):
    out, g = [], (da - timedelta(days=1)).date()
    while g <= a.date():
        for hhmm in orari_del_giorno(pag, g):
            h, m = map(int, hhmm.split(":"))
            t = datetime(g.year, g.month, g.day, h, m, tzinfo=tz)
            if da <= t <= a:
                out.append(t)
        g += timedelta(days=1)
    return sorted(out)


def chiave(t):
    return t.strftime("%Y-%m-%d %H:%M")


def prossimo_video(nome, coda, st):
    usati = set(st["usati"]) | set(st.get("scartati", {}))
    for r in coda:
        if r["id"] not in usati and (PAGINE / nome / "coda" / r["file"]).exists():
            return r
    return None


# ================================================================ esecuzione
def pubblica_video(meta, pag, nome, r, st, prova):
    video = PAGINE / nome / "coda" / r["file"]
    durata = float(r.get("durata") or 0)
    audio, info, aid = None, "audio disattivato", r.get("audio_id") or None
    a = pag.get("audio") or {}
    if a.get("attivo", True) and not aid:
        audio, info = scegli_audio(meta, pag, durata, st, r.get("ricerca_audio") or None)
        if audio is None and not a.get("pubblica_senza_audio", False):
            raise ErroreAPI(f"nessun audio adatto ({info})", temporaneo=True)
        aid = audio and str(audio.get("audio_id") or audio.get("id"))
    cfg_audio = {"audio_id": str(aid), "audio_volume": int(a.get("volume_audio", 100)),
                 "video_volume": int(a.get("volume_video", 1))} if aid else None
    descr = descrivi_audio(audio) if audio else (aid or "-")
    print(f"   {r['id']} ({r['file']}) | audio: {descr} [{info}]")
    if prova:
        return {"esito": "prova", "id": r["id"], "audio": descr}
    cid = meta.crea_container(pag["ig_user_id"], r.get("caption", ""), cfg_audio,
                              share_to_feed=pag.get("anche_nel_feed", True))
    meta.carica_file(cid, str(video))
    meta.aspetta_pronto(cid)
    media_id = meta.pubblica(pag["ig_user_id"], cid)
    link = ""
    try:
        link = meta.get(media_id, fields="permalink").get("permalink", "")
    except ErroreAPI:
        pass
    if aid:
        st["audio_usati"] = (st["audio_usati"] + [str(aid)])[-200:]
    return {"esito": "pubblicato", "id": r["id"], "file": r["file"], "media_id": media_id,
            "link": link, "audio": descr, "audio_id": aid}


def esegui(prova=False, adesso=None):
    g = cfg_generale()
    tz = ZoneInfo(g["fuso_orario"])
    adesso = adesso or datetime.now(tz)
    for nome in elenco_pagine():
        pag = cfg_pagina(nome)
        if not pag["attiva"]:
            continue
        st = leggi_stato(nome)
        if not st.get("dal"):
            st["dal"] = adesso.isoformat(timespec="minutes")   # i turni prima dell'attivazione non contano
        inizio = max(datetime.fromisoformat(st["dal"]), adesso - timedelta(days=2))
        if pag.get("inizia_dal"):  # turni automatici solo da questa data (es. per partire "da domani")
            inizio = max(inizio, datetime.fromisoformat(str(pag["inizia_dal"])).replace(tzinfo=tz))
        finestra = timedelta(minutes=int(pag.get("finestra_minuti", g["finestra_minuti"])))
        turni = [t for t in turni_tra(pag, inizio, adesso, tz) if chiave(t) not in st["turni"]]
        # turni troppo vecchi → mancati
        for t in [t for t in turni if adesso - t > finestra]:
            st["turni"][chiave(t)] = {"esito": "mancato",
                                      "motivo": "; ".join(e["errore"][:120] for e in st["errori"].get(chiave(t), [])[-1:])
                                      or "nessuna esecuzione in tempo"}
            print(f"[{nome}] turno {chiave(t)} mancato")
        validi = [t for t in turni if adesso - t <= finestra]
        n_max = max(1, int(g["max_per_esecuzione"]))
        # più turni arretrati insieme: esce solo il più recente, gli altri sono mancati (niente Reel attaccati)
        for t in validi[:-n_max]:
            st["turni"][chiave(t)] = {"esito": "mancato", "motivo": "più turni arretrati: pubblicato solo il più recente"}
            print(f"[{nome}] turno {chiave(t)} mancato (accorpato al successivo)")
        da_fare = validi[-n_max:]
        if not da_fare:
            scrivi_stato(nome, st)
            continue
        coda = leggi_coda(nome)
        token = token_per(pag)
        meta = Meta(token, g["api_version"]) if token else None
        for t in da_fare:
            k = chiave(t)
            r = prossimo_video(nome, coda, st)
            print(f"[{nome}] turno {k}")
            if r is None:
                st["turni"][k] = {"esito": "coda_vuota"}
                print("   ⚠ coda vuota: nessun video da pubblicare")
                continue
            if meta is None:
                st["errori"].setdefault(k, []).append({"errore": f"manca il token {pag['token_env']}", "temporaneo": True})
                print(f"   ❌ manca il token ({pag['token_env']})")
                continue
            try:
                ris = pubblica_video(meta, pag, nome, r, st, prova)
                if prova:
                    continue
                ris["ora"] = datetime.now(tz).isoformat(timespec="minutes")
                st["turni"][k] = ris
                st["usati"].append(r["id"])
                st["errori"].pop(k, None)
                print(f"   ✅ pubblicato: {ris['link'] or ris['media_id']}")
                if pag.get("elimina_dopo", True):
                    (PAGINE / nome / "coda" / r["file"]).unlink(missing_ok=True)
            except Exception as e:  # noqa: BLE001 — qualsiasi errore va registrato, non deve fermare le altre pagine
                temp = getattr(e, "temporaneo", False) or e.__class__.__module__.startswith("requests")
                st["errori"].setdefault(k, []).append({"quando": datetime.now(tz).isoformat(timespec="minutes"),
                                                       "video": r["id"], "errore": str(e)[:500], "temporaneo": temp})
                st["errori"][k] = st["errori"][k][-10:]
                print(f"   ❌ {'(riprovo al prossimo controllo) ' if temp else ''}{e}")
                if not temp:
                    # problema del VIDEO (es. elaborazione fallita): lo scarto, il turno userà il successivo
                    st.setdefault("scartati", {})[r["id"]] = str(e)[:300]
        scrivi_stato(nome, st)
    pannello(stampa=False)


def subito(nome, prova=False):
    """Pubblica ADESSO il prossimo video della coda (fuori dagli orari)."""
    g = cfg_generale()
    tz = ZoneInfo(g["fuso_orario"])
    pag, st, coda = cfg_pagina(nome), leggi_stato(nome), leggi_coda(nome)
    adesso = datetime.now(tz)
    st["dal"] = st.get("dal") or adesso.isoformat(timespec="minutes")
    r = prossimo_video(nome, coda, st)
    if r is None:
        print(f"[{nome}] coda vuota: niente da pubblicare")
        return 1
    token = token_per(pag)
    if not token:
        print(f"[{nome}] manca il token ({pag['token_env']})")
        return 1
    k = f"{adesso:%Y-%m-%d %H:%M} (subito)"
    print(f"[{nome}] pubblicazione immediata")
    try:
        ris = pubblica_video(Meta(token, g["api_version"]), pag, nome, r, st, prova)
        if prova:
            return 0
        ris["ora"] = datetime.now(tz).isoformat(timespec="minutes")
        st["turni"][k] = ris
        st["usati"].append(r["id"])
        print(f"   ✅ pubblicato: {ris['link'] or ris['media_id']}")
        if pag.get("elimina_dopo", True):
            (PAGINE / nome / "coda" / r["file"]).unlink(missing_ok=True)
        return 0
    except Exception as e:  # noqa: BLE001
        print(f"   ❌ {e}")
        st["errori"].setdefault(k, []).append({"quando": adesso.isoformat(timespec="minutes"), "video": r["id"],
                                               "errore": str(e)[:500], "temporaneo": getattr(e, "temporaneo", False)})
        if not getattr(e, "temporaneo", False) and "elaborazione" in str(e):
            st.setdefault("scartati", {})[r["id"]] = str(e)[:300]
        return 1
    finally:
        scrivi_stato(nome, st)
        pannello(stampa=False)


# ================================================================ pannello
def pannello(stampa=True):
    g = cfg_generale()
    tz = ZoneInfo(g["fuso_orario"])
    adesso = datetime.now(tz)
    righe, avvisi = [], []
    for nome in elenco_pagine():
        pag, st, coda = cfg_pagina(nome), leggi_stato(nome), leggi_coda(nome)
        usati = set(st["usati"]) | set(st.get("scartati", {}))
        in_coda = [r for r in coda if r["id"] not in usati and (PAGINE / nome / "coda" / r["file"]).exists()]
        oggi = orari_del_giorno(pag, adesso.date())
        al_giorno = len(oggi) or 1
        da = adesso
        if pag.get("inizia_dal"):
            da = max(da, datetime.fromisoformat(str(pag["inizia_dal"])).replace(tzinfo=tz))
        prossimi = [t for t in turni_tra(pag, da, da + timedelta(days=7), tz)]
        ultimi = [(k, v) for k, v in sorted(st["turni"].items())][-1:]
        settimana = [v for k, v in st["turni"].items() if k >= chiave(adesso - timedelta(days=7))]
        pubbl = sum(1 for v in settimana if v.get("esito") == "pubblicato")
        problemi = sum(1 for v in settimana if v.get("esito") in ("mancato", "coda_vuota"))
        giorni = len(in_coda) / al_giorno
        stato_txt = "✅ attiva" if pag["attiva"] else "⏸ in pausa"
        if pag["attiva"] and giorni < 2:
            avvisi.append(f"**{pag['nome']}**: coda quasi finita ({len(in_coda)} video ≈ {giorni:.1f} giorni)")
        if pag["attiva"] and str(pag.get("ig_user_id", "")).startswith("DA_"):
            avvisi.append(f"**{pag['nome']}**: manca l'ID dell'account Instagram in pagina.yaml")
        for k, v in st["errori"].items():
            if v and k >= chiave(adesso - timedelta(days=1)) and k not in st["turni"]:
                avvisi.append(f"**{pag['nome']}** turno {k}: {v[-1]['errore'][:140]}")
        righe.append({
            "Pagina": pag["nome"], "Stato": stato_txt,
            "Orari oggi": ", ".join(oggi) or "-",
            "Post/giorno": len(oggi),
            "In coda": len(in_coda), "Copertura": f"{giorni:.1f} gg",
            "Prossimo": (f"{GIORNI[prossimi[0].weekday()][:3]} {prossimi[0]:%H:%M}") if prossimi and pag["attiva"] else "-",
            "Ultimo": (f"{ultimi[0][0][5:]} {'✅' if ultimi[0][1].get('esito') == 'pubblicato' else '⚠ ' + ultimi[0][1].get('esito', '')}"
                       if ultimi else "-"),
            "Ultimi 7gg": f"{pubbl} pubblicati" + (f", {problemi} saltati" if problemi else ""),
        })
    cols = list(righe[0].keys()) if righe else ["Pagina"]
    md = [f"# Pannello Auto Edit & Post\n", f"Aggiornato: {adesso:%d/%m/%Y %H:%M}\n",
          "| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    md += ["| " + " | ".join(str(r[c]) for c in cols) + " |" for r in righe]
    if avvisi:
        md += ["\n## ⚠ Da guardare"] + [f"- {a}" for a in avvisi]
    else:
        md += ["\n✅ Nessun problema."]
    # ultimi post pubblicati (tutte le pagine)
    tutti = []
    for nome in elenco_pagine():
        for k, v in leggi_stato(nome)["turni"].items():
            if v.get("esito") == "pubblicato":
                tutti.append((k, cfg_pagina(nome)["nome"], v))
    if tutti:
        md += ["\n## Ultimi post", "| Quando | Pagina | Audio | Link |", "|---|---|---|---|"]
        md += [f"| {k} | {p} | {v.get('audio', '-')} | {v.get('link') or v.get('media_id')} |"
               for k, p, v in sorted(tutti, reverse=True)[:20]]
    testo = "\n".join(md) + "\n"
    (BASE / "PANNELLO.md").write_text(testo, encoding="utf-8")
    if stampa:
        print(testo)


# ================================================================ gestione pagine e coda
MODELLO_PAGINA = """# Pagina: {nome}
nome: "{nome}"
attiva: false                     # metti true quando ID e token sono pronti
ig_user_id: "DA_INSERIRE"         # ID numerico dell'account Instagram
token_env: TOKEN_META             # nome del secret con il token (uno solo per tutte le pagine dello stesso portfolio)
anche_nel_feed: true
elimina_dopo: true                # cancella il video dopo averlo pubblicato

# ORARI FISSI (ora italiana). A ogni orario esce il prossimo video della coda.
orari:
  ogni_giorno: ["08:15", "12:45", "18:30", "21:00"]
  # per giorni diversi basta aggiungere il giorno (sostituisce ogni_giorno quel giorno):
  # sabato: ["10:00", "13:00", "18:00", "21:30"]
  # domenica: ["11:00", "20:30"]

hashtag: ""                       # aggiunti in fondo a ogni caption
caption: []                       # caption a rotazione (se il video non ne ha una sua)

audio:
  attivo: true
  tipo: music                     # music | original_sound
  ricerca: []                     # vuoto = TENDENZA; es. ["natale", "christmas"]
  tra_i_primi: 5
  no_ripetere_ultimi: 10
  volume_audio: 100
  volume_video: 1
  vietati: []
  pubblica_senza_audio: false
"""


def nuova(nome, titolo):
    d = PAGINE / nome
    if (d / "pagina.yaml").exists():
        sys.exit(f"la pagina {nome} esiste già")
    (d / "coda").mkdir(parents=True, exist_ok=True)
    (d / "pagina.yaml").write_text(MODELLO_PAGINA.format(nome=titolo or nome), encoding="utf-8")
    scrivi_coda(nome, [])
    print(f"Creata pagine/{nome}/ — compila pagina.yaml (ID, orari, hashtag) e metti attiva: true")


def _durata(p):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
                       capture_output=True, text=True)
    return float(r.stdout.strip())


def _comprimi(src, dst):
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(src),
                    "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
                    "-map", "0:v", "-map", "1:a", "-shortest",
                    "-c:v", "libx264", "-preset", "medium", "-crf", "22", "-maxrate", "3.5M", "-bufsize", "7M",
                    "-pix_fmt", "yuv420p", "-r", "30", "-c:a", "aac", "-b:a", "64k",
                    "-movflags", "+faststart", "-map_metadata", "-1", str(dst)], check=True)


def _captions_da_testi(path):
    caps, tags, sez = [], "", None
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if re.match(r"^\[.+\]$", s):
            sez = s
        elif sez == "[post]" and s.startswith("caption:"):
            caps.append(s.split(":", 1)[1].strip())
        elif sez == "[post]" and s.startswith("hashtag:"):
            tags = s.split(":", 1)[1].strip()
    return caps, tags


def aggiungi(nome, cartelle, testi=None, ricerca_audio="", seed=None, quanti=None):
    if not (PAGINE / nome / "pagina.yaml").exists():
        sys.exit(f"pagina {nome} inesistente (crea con: nuova {nome})")
    pag, rng = cfg_pagina(nome), random.Random(seed)
    coda = leggi_coda(nome)
    gia = {r.get("origine") for r in coda}
    caps, tags = list(pag.get("caption") or []), pag.get("hashtag") or ""
    for t in testi or []:
        c, h = _captions_da_testi(t)
        caps += c
        tags = tags or h
    caps = caps or [""]
    # alterna i video tra le cartelle (prodotti diversi non escono mai tutti di fila)
    pool = []
    for d in cartelle:
        v = sorted(str(p.resolve()) for p in Path(d).glob("*.mp4") if str(p.resolve()) not in gia)
        rng.shuffle(v)
        pool.append(v)
    ordine = []
    while any(pool):
        for v in pool:
            if v:
                ordine.append(v.pop())
    if quanti:
        ordine = ordine[:quanti]
    n0 = max([int(r["id"].rsplit("-", 1)[-1]) for r in coda] or [0])
    for i, src in enumerate(ordine, 1):
        pid = f"{nome}-{n0 + i:05d}"
        dst = PAGINE / nome / "coda" / f"{pid}.mp4"
        _comprimi(src, dst)
        coda.append({"id": pid, "file": dst.name, "durata": f"{_durata(dst):.2f}",
                     "caption": (caps[(len(coda)) % len(caps)] + ("\n\n" + tags if tags else "")).strip(),
                     "ricerca_audio": ricerca_audio, "audio_id": "", "origine": src,
                     "aggiunto": date.today().isoformat()})
        print(f"+ {pid}  {Path(src).name}  ({dst.stat().st_size / 1e6:.1f} MB)")
    scrivi_coda(nome, coda)
    print(f"\n{len(ordine)} video aggiunti alla coda di {pag['nome']}")
    pannello(stampa=False)


ESTENSIONI_AUDIO = (".mp3", ".m4a", ".aac", ".wav", ".ogg", ".mp4", ".mov")


def metti_audio(nome, rifai=False):
    """Inserisce un audio vero DENTRO ogni video in coda (a rotazione da pagine/<pagina>/audio/).
    Così il reel non esce mai muto, anche se Meta ignora la musica di tendenza."""
    cart = PAGINE / nome / "audio"
    tracce = sorted(p for p in cart.glob("*") if p.suffix.lower() in ESTENSIONI_AUDIO) if cart.exists() else []
    if not tracce:
        sys.exit(f"nessun audio in pagine/{nome}/audio/ (mp3, m4a, wav o anche video mp4 da cui prendere l'audio)")
    durate = {t.name: _durata(t) for t in tracce}
    coda = leggi_coda(nome)
    uso = {t.name: 0 for t in tracce}
    for r in coda:
        if r.get("audio_file") in uso:
            uso[r["audio_file"]] += 1
    prec, fatti = None, 0
    for r in coda:
        if r.get("audio_file") and not rifai:
            prec = r["audio_file"]
            continue
        vid = PAGINE / nome / "coda" / r["file"]
        if not vid.exists():
            continue
        d = _durata(vid)
        # meno usata, mai uguale alla precedente; preferisce tracce lunghe almeno quanto il video
        cand = sorted(tracce, key=lambda t: (t.name == prec, durate[t.name] + 0.2 < d, uso[t.name], random.random()))
        t = cand[0]
        tmp = vid.with_suffix(".tmp.mp4")
        loop = ["-stream_loop", "-1"] if durate[t.name] + 0.2 < d else []
        fade = max(d - 0.6, 0)
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(vid), *loop, "-i", str(t),
                        "-map", "0:v", "-map", "1:a:0", "-t", f"{d:.3f}",
                        "-af", f"afade=t=in:d=0.05,afade=t=out:st={fade:.3f}:d=0.6,loudnorm=I=-14:TP=-1.5",
                        "-c:v", "copy", "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2",
                        "-movflags", "+faststart", str(tmp)], check=True)
        tmp.replace(vid)
        r["audio_file"] = t.name
        uso[t.name] += 1
        prec = t.name
        fatti += 1
        print(f"♪ {r['id']}  ←  {t.name}")
    scrivi_coda(nome, coda)
    print(f"\n{fatti} video con audio inserito ({len(tracce)} tracce a rotazione)")


# ================================================================ orari GitHub Actions
def cron():
    """Workflow GitHub che parte solo agli orari delle pagine (valido con ora solare E legale)."""
    g = cfg_generale()
    tz = ZoneInfo(g["fuso_orario"])
    orari = set()
    for nome in elenco_pagine():
        pag = cfg_pagina(nome)
        if not pag["attiva"]:
            continue
        for k, lista in (pag.get("orari") or {}).items():
            orari |= {str(x) for x in lista}
    # offset UTC dell'ora solare e legale del fuso (es. +1 e +2 per l'Italia)
    anno = date.today().year
    offsets = {int(datetime(anno, m, 15, 12, tzinfo=tz).utcoffset().total_seconds() // 60) for m in (1, 7)}
    per_minuto = {}
    for hhmm in sorted(orari):
        h, m = map(int, hhmm.split(":"))
        for off in offsets:
            tot = (h * 60 + m - off + 5) % (24 * 60)          # +5 minuti di margine dopo l'orario
            per_minuto.setdefault(tot % 60, set()).add(tot // 60)
    righe = [f'    - cron: "{mi} {",".join(map(str, sorted(hs)))} * * *"' for mi, hs in sorted(per_minuto.items())]
    wf = f"""name: Pubblica Reel
# GENERATO da `python piattaforma.py cron` — non modificare a mano: cambia gli orari in pagine/*/pagina.yaml
on:
  schedule:
{chr(10).join(righe) if righe else '    - cron: "0 3 * * *"'}
  workflow_dispatch:
    inputs:
      comando:
        description: "esegui | subito <pagina> | esegui --prova | pannello | verifica | audio <pagina> <parole>"
        required: false
        default: "esegui"

concurrency:
  group: pubblica
  cancel-in-progress: false

permissions:
  contents: write

jobs:
  pubblica:
    runs-on: ubuntu-latest
    timeout-minutes: 45
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -r requirements.txt
      - name: Esegui
        env:
          SEGRETI: ${{{{ toJSON(secrets) }}}}
          COMANDO: ${{{{ github.event.inputs.comando || 'esegui' }}}}
        run: python piattaforma.py $COMANDO
      - name: Salva stato
        if: always()
        run: |
          git config user.name "auto-edit-post"
          git config user.email "auto-edit-post@users.noreply.github.com"
          git add -A pagine PANNELLO.md
          git diff --cached --quiet || (git commit -m "pubblicazioni $(date -u +%F' '%H:%M)" && git pull --rebase && git push)
"""
    p = BASE / ".github" / "workflows" / "pubblica.yml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(wf, encoding="utf-8")
    print(f"Orari GitHub aggiornati: {len(orari)} orari distinti → {sum(len(h) for h in per_minuto.values())} avvii al giorno")
    print("\n".join(righe))


# ================================================================ servizio
def verifica():
    g = cfg_generale()
    for nome in elenco_pagine():
        pag = cfg_pagina(nome)
        tok = token_per(pag)
        if not tok:
            print(f"[{nome}] manca il token ({pag['token_env']})")
            continue
        m = Meta(tok, g["api_version"])
        try:
            info = m.get(pag["ig_user_id"], fields="username,followers_count")
            q = m.get(f"{pag['ig_user_id']}/content_publishing_limit", fields="config,quota_usage")
            print(f"[{nome}] account OK: @{info.get('username')} ({info.get('followers_count')} follower)")
            print(f"[{nome}] quota pubblicazioni: {q}")
            try:
                dbg = m.get("debug_token", input_token=tok).get("data", {})
                scade = dbg.get("expires_at") or 0
                scade_txt = "mai" if not scade else datetime.fromtimestamp(scade).strftime("%Y-%m-%d")
                print(f"[{nome}] token {'valido' if dbg.get('is_valid') else 'NON valido'}, scade: {scade_txt}, "
                      f"permessi: {', '.join(dbg.get('scopes', []))}")
            except ErroreAPI as e:
                print(f"[{nome}] (dettagli token non disponibili: {e})")
        except Exception as e:  # noqa: BLE001
            print(f"[{nome}] ERRORE: {e}")


def audio(nome, parole):
    g = cfg_generale()
    pag = cfg_pagina(nome)
    m = Meta(token_per(pag), g["api_version"])
    if "--grezzo" in parole:
        # risposta completa di Meta, per capire formato/permessi
        parole = [p for p in parole if p != "--grezzo"]
        for tipo in ("music", "original_sound"):
            for q in (parole or [None]):
                params = {"audio_type": tipo, "user_id": pag["ig_user_id"]}
                if q:
                    params["search_query"] = q
                try:
                    r = m.s.get(f"{lib_meta.GRAPH}/{m.v}/ig_audio",
                                params={**params, "access_token": m.token}, timeout=60)
                    print(f"\n== GREZZO {tipo} «{q or 'tendenza'}» → HTTP {r.status_code}")
                    print(r.text[:3000])
                except Exception as e:  # noqa: BLE001
                    print(f"== GREZZO {tipo}: errore di rete {e}")
        return
    for tipo in ("music", "original_sound"):
        for q in (parole or [None]):
            try:
                res = m.cerca_audio(pag["ig_user_id"], tipo, q)
            except Exception as e:  # noqa: BLE001
                print(f"{tipo} «{q or 'tendenza'}»: ERRORE {e}")
                continue
            print(f"\n== {tipo} — {'ricerca: ' + q if q else 'di tendenza'} ({len(res)} risultati)")
            for x in res[:25]:
                print(f"  {x.get('audio_id') or x.get('id')}  {(x.get('duration_in_ms') or 0) / 1000:5.0f}s  {descrivi_audio(x)}")


def info(nome, media_id):
    """Diagnostica di un post pubblicato: risposta grezza di Meta, salvata anche in pagine/_diagnostica.txt."""
    g = cfg_generale()
    pag = cfg_pagina(nome)
    m = Meta(token_per(pag), g["api_version"])
    righe = [f"# info {nome} {media_id} — {datetime.now().isoformat(timespec='seconds')}"]
    for campi in ("id,media_type,media_product_type,media_audio_type,permalink,timestamp,caption",
                  "id,media_type,media_product_type,permalink,timestamp",
                  "audio,music_metadata,copyright_check_information"):
        r = m.s.get(f"{lib_meta.GRAPH}/{m.v}/{media_id}",
                    params={"fields": campi, "access_token": m.token}, timeout=60)
        righe.append(f"\n== fields={campi} → HTTP {r.status_code}\n{r.text[:3000]}")
    testo = "\n".join(righe)
    print(testo)
    (BASE / "pagine" / "_diagnostica.txt").write_text(testo + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description="Auto Edit & Post")
    sub = ap.add_subparsers(dest="cmd")
    e = sub.add_parser("esegui"); e.add_argument("--prova", action="store_true")
    sub.add_parser("pannello")
    n = sub.add_parser("nuova"); n.add_argument("pagina"); n.add_argument("titolo", nargs="?", default="")
    a = sub.add_parser("aggiungi"); a.add_argument("pagina"); a.add_argument("cartelle", nargs="+")
    a.add_argument("--testi", nargs="*", default=[]); a.add_argument("--ricerca-audio", default="")
    a.add_argument("--quanti", type=int); a.add_argument("--seed", type=int)
    sub.add_parser("cron")
    su = sub.add_parser("subito"); su.add_argument("pagina"); su.add_argument("--prova", action="store_true")
    sub.add_parser("verifica")
    au = sub.add_parser("audio"); au.add_argument("pagina"); au.add_argument("parole", nargs="*")
    au.add_argument("--grezzo", action="store_true", help="mostra la risposta completa di Meta")
    ma = sub.add_parser("metti-audio"); ma.add_argument("pagina"); ma.add_argument("--rifai", action="store_true")
    inf = sub.add_parser("info"); inf.add_argument("pagina"); inf.add_argument("media_id")
    x = ap.parse_args()
    if x.cmd == "esegui":
        esegui(prova=x.prova)
    elif x.cmd == "pannello":
        pannello()
    elif x.cmd == "nuova":
        nuova(x.pagina, x.titolo)
    elif x.cmd == "aggiungi":
        aggiungi(x.pagina, x.cartelle, x.testi, x.ricerca_audio, x.seed, x.quanti)
    elif x.cmd == "subito":
        sys.exit(subito(x.pagina, x.prova))
    elif x.cmd == "cron":
        cron()
    elif x.cmd == "verifica":
        verifica()
    elif x.cmd == "metti-audio":
        metti_audio(x.pagina, x.rifai)
    elif x.cmd == "info":
        info(x.pagina, x.media_id)
    elif x.cmd == "audio":
        audio(x.pagina, x.parole + (["--grezzo"] if x.grezzo else []))
    else:
        ap.print_help()


if __name__ == "__main__":
    main()

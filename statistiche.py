"""Statistiche dei reel pubblicati dal bot: views, like, commenti, condivisioni, salvataggi e commenti con la parola chiave.
uso: python piattaforma.py statistiche [pagina ...] [--giorni N]
Scrive pagine/_statistiche/<pagina>.csv e pagine/_statistiche/RIEPILOGO.md"""
import csv, re
from datetime import datetime, timedelta

import lib_meta
from lib_meta import ErroreAPI, Meta

NOTE = []
CAMPI = ["pubblicato", "turno", "piattaforma", "reel", "media_id", "link", "views", "reach", "like", "commenti",
         "condivisioni", "salvati", "commenti_cta", "audio", "caption"]


def _ig(m, mid, parola):
    d, err = {}, []
    for metriche in ("views,reach,likes,comments,shares,saved", "plays,reach,likes,comments,shares,saved",
                     "reach,likes,comments,shares,saved"):
        try:
            r = m.get(f"{mid}/insights", metric=metriche)
            for x in r.get("data", []):
                d[x["name"]] = (x.get("values") or [{}])[0].get("value", x.get("total_value", {}).get("value"))
            break
        except ErroreAPI as e:
            err.append(f"{metriche.split(',')[0]}: {str(e)[:160]}")
            continue
    NOTE.extend(err[:1])
    if not d:
        try:
            r = m.get(mid, fields="like_count,comments_count")
            d = {"likes": r.get("like_count"), "comments": r.get("comments_count")}
        except ErroreAPI as e:
            d = {"errore": str(e)[:120]}
    cta = ""
    if parola:
        try:
            testi = [c.get("text", "") for c in m.get(f"{mid}/comments", fields="text", limit=100).get("data", [])]
            cta = sum(1 for t in testi if parola.lower() in t.lower())
        except ErroreAPI:
            pass
    return {"views": d.get("views", d.get("plays", "")), "reach": d.get("reach", ""), "like": d.get("likes", ""),
            "commenti": d.get("comments", ""), "condivisioni": d.get("shares", ""), "salvati": d.get("saved", ""),
            "commenti_cta": cta}


def _fb(m, page_id, vid, parola):
    tok = m.token_pagina(page_id)
    mp = Meta(tok, m.v)
    d = {}
    try:
        r = mp.get(f"{vid}/video_insights")
        for x in r.get("data", []):
            v = (x.get("values") or [{}])[0].get("value")
            d[x["name"]] = v
    except ErroreAPI as e:
        d["errore"] = str(e)[:120]; NOTE.append("FB video_insights: " + str(e)[:200])
    like = com = cta = ""
    try:
        r = mp.get(vid, fields="likes.summary(true).limit(0),comments.summary(true).limit(100){message}")
        like = (r.get("likes") or {}).get("summary", {}).get("total_count", "")
        cc = r.get("comments") or {}
        com = cc.get("summary", {}).get("total_count", "")
        if parola:
            cta = sum(1 for c in cc.get("data", []) if parola.lower() in (c.get("message") or "").lower())
    except ErroreAPI:
        pass
    reaz = d.get("post_video_likes_by_reaction_type")
    if isinstance(reaz, dict) and like == "":
        like = sum(reaz.values())
    soc = d.get("post_video_social_actions") or {}
    return {"views": d.get("blue_reels_play_count", d.get("fb_reels_total_plays", "")),
            "reach": d.get("post_impressions_unique", ""), "like": like, "commenti": com,
            "condivisioni": soc.get("SHARE", soc.get("share", "")) if isinstance(soc, dict) else "",
            "salvati": "", "commenti_cta": cta}


def statistiche(P, pagine=None, giorni=7):
    g = P.cfg_generale()
    out_dir = P.PAGINE / "_statistiche"
    out_dir.mkdir(exist_ok=True)
    riepilogo = [f"# Statistiche reel — {datetime.now().strftime('%d/%m/%Y %H:%M')} (ultimi {giorni} giorni)\n"]
    for nome in (pagine or P.elenco_pagine()):
        pag = P.cfg_pagina(nome)
        st = P.leggi_stato(nome)
        coda = {r["id"]: r for r in P.leggi_coda(nome)}
        m = Meta(P.token_per(pag), g["api_version"])
        cta_txt = str(pag.get("caption_cta") or "")
        parola = (re.findall(r"[Cc]ommenta\s+[\"“«]?([A-ZÀ-Ü]{3,})", cta_txt) or [""])[0]
        limite = datetime.now() - timedelta(days=giorni)
        righe = []
        for k, t in sorted(st.get("turni", {}).items()):
            if not isinstance(t, dict) or t.get("esito") != "pubblicato" or not t.get("media_id"):
                continue
            try:
                if datetime.fromisoformat(k[:16].replace(" ", "T")) < limite:
                    continue
            except ValueError:
                pass
            r = coda.get(t.get("id"), {})
            reel = (r.get("origine") or t.get("file") or "").split("/")[-1]
            fb = t.get("piattaforma") == "facebook"
            try:
                met = _fb(m, pag["fb_page_id"], t["media_id"], parola) if fb else _ig(m, t["media_id"], parola)
            except Exception as e:  # noqa: BLE001
                met = {"views": f"errore: {str(e)[:80]}"}
            righe.append({"pubblicato": k, "turno": k[-5:], "piattaforma": "FB" if fb else "IG", "reel": reel,
                          "media_id": t["media_id"], "link": t.get("link", ""), "audio": t.get("audio_file") or t.get("audio", ""),
                          "caption": (r.get("caption") or "").replace("\n", " ")[:80], **met})
        if not righe:
            continue
        with open(out_dir / f"{nome}.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=CAMPI, extrasaction="ignore"); w.writeheader(); w.writerows(righe)
        num = lambda x: x if isinstance(x, (int, float)) else -1
        top = sorted(righe, key=lambda x: num(x.get("views")), reverse=True)
        riepilogo.append(f"\n## {pag.get('nome', nome)} — {len(righe)} reel (parola CTA: {parola or '-'})\n")
        riepilogo.append("| reel | quando | views | like | commenti | cta | condiv. | audio |\n|---|---|---|---|---|---|---|---|")
        for x in top:
            riepilogo.append(f"| {x['reel'][:34]} | {x['pubblicato'][5:16]} | {x.get('views','')} | {x.get('like','')} | "
                             f"{x.get('commenti','')} | {x.get('commenti_cta','')} | {x.get('condivisioni','')} | {str(x.get('audio',''))[:24]} |")
        print(f"✓ {nome}: {len(righe)} reel")
    if NOTE:
        riepilogo.append("\n## Errori Meta (primi)\n" + "\n".join(f"- {x}" for x in list(dict.fromkeys(NOTE))[:6]))
    (out_dir / "RIEPILOGO.md").write_text("\n".join(riepilogo) + "\n", encoding="utf-8")
    print("\n".join(riepilogo))

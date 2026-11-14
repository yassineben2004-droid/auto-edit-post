"""Controllo SOLO LETTURA di una pagina: token, account Instagram, Pagina Facebook, permessi. Non pubblica nulla.
Uso: python verifica_pagina.py <pagina>   (scrive anche pagine/_prova_<pagina>.txt)"""
import sys
from piattaforma import cfg_generale, cfg_pagina, token_per, PAGINE
from lib_meta import Meta

nome = sys.argv[1]
pag, g = cfg_pagina(nome), cfg_generale()
righe = []
def ok(msg): righe.append("✅ " + msg)
def no(msg): righe.append("❌ " + msg)

tok = token_per(pag)
if not tok:
    no(f"manca il token {pag['token_env']}")
else:
    m = Meta(tok, g["api_version"])
    try:
        perm = m.get("me/permissions").get("data", [])
        concessi = sorted(p["permission"] for p in perm if p.get("status") == "granted")
        ok("permessi del token: " + ", ".join(concessi))
        for p in ["instagram_content_publish", "instagram_basic", "pages_manage_posts", "pages_read_engagement", "pages_show_list"]:
            (ok if p in concessi else no)(f"permesso {p}")
    except Exception as e: no(f"lettura permessi: {e}")
    try:
        ig = m.get(pag["ig_user_id"], fields="username,name")
        ok(f"Instagram raggiungibile: @{ig.get('username')} ({ig.get('name')})")
    except Exception as e: no(f"Instagram {pag['ig_user_id']}: {e}")
    fb = (pag.get("facebook") or {}).get("fb_page_id")
    if fb:
        try:
            p = m.get(fb, fields="name,instagram_business_account")
            ok(f"Pagina Facebook raggiungibile: {p.get('name')}")
            iga = (p.get("instagram_business_account") or {}).get("id")
            (ok if iga == pag["ig_user_id"] else no)(f"Instagram collegato alla Pagina: {iga}")
        except Exception as e: no(f"Pagina {fb}: {e}")
        try:
            m.token_pagina(fb); ok("token della Pagina ottenuto (può pubblicare Reel su FB)")
        except Exception as e: no(f"token della Pagina: {e}")
        try:
            acc = m.get("me/accounts", fields="id,name,tasks", limit=100).get("data", [])
            t = next((a for a in acc if a["id"] == fb), None)
            (ok if t else no)(f"Pagina tra quelle del token; ruoli: {t.get('tasks') if t else '-'}")
        except Exception as e: no(f"me/accounts: {e}")
testo = "\n".join(righe)
print(testo)
(PAGINE / f"_prova_{nome}.txt").write_text(testo + "\n", encoding="utf-8")

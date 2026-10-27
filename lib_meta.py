"""Chiamate alle API Meta (Instagram) + scelta audio. Usato da piattaforma.py."""
import json, os, random, time

import requests

GRAPH = "https://graph.facebook.com"
RUPLOAD = "https://rupload.facebook.com"


# ---------------------------------------------------------------- API Meta
class ErroreAPI(Exception):
    def __init__(self, msg, temporaneo=False):
        super().__init__(msg)
        self.temporaneo = temporaneo  # True = riprova ai giri successivi senza contarlo


class Meta:
    def __init__(self, token, versione):
        self.token, self.v = token, versione
        self.s = requests.Session()

    def _chk(self, r):
        try:
            data = r.json()
        except ValueError:
            data = {"raw": r.text[:300]}
        if r.status_code >= 400 or (isinstance(data, dict) and "error" in data):
            err = data.get("error", data) if isinstance(data, dict) else data
            temp = r.status_code >= 500 or r.status_code == 429 or (
                isinstance(err, dict) and (err.get("is_transient") or err.get("code") in (1, 2, 4, 17, 32, 613)))
            raise ErroreAPI(f"HTTP {r.status_code}: {json.dumps(err, ensure_ascii=False)[:500]}", temporaneo=bool(temp))
        return data

    def get(self, path, **params):
        params["access_token"] = self.token
        return self._chk(self.s.get(f"{GRAPH}/{self.v}/{path}", params=params, timeout=60))

    def post(self, path, **data):
        data["access_token"] = self.token
        return self._chk(self.s.post(f"{GRAPH}/{self.v}/{path}", data=data, timeout=120))

    # --- audio
    def cerca_audio(self, ig_user_id, tipo="music", ricerca=None):
        params = {"audio_type": tipo, "user_id": ig_user_id}
        if ricerca:
            params["search_query"] = ricerca
        res = self.get("ig_audio", **params)
        if isinstance(res, list):
            return res
        # la documentazione dice "data", ma Meta in realtà risponde con "audio": accetto entrambi
        return res.get("audio") or res.get("data") or []

    # --- reel
    def crea_container(self, ig_user_id, caption, audio_cfg, share_to_feed=True, video_url=None):
        data = {"media_type": "REELS", "caption": caption, "share_to_feed": "true" if share_to_feed else "false"}
        if video_url:
            data["video_url"] = video_url
        else:
            data["upload_type"] = "resumable"
        if audio_cfg:
            data["audio_configuration"] = json.dumps(audio_cfg)
        return self.post(f"{ig_user_id}/media", **data)["id"]

    def carica_file(self, container_id, path):
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            r = self.s.post(f"{RUPLOAD}/ig-api-upload/{self.v}/{container_id}",
                            headers={"Authorization": f"OAuth {self.token}", "offset": "0",
                                     "file_size": str(size)},
                            data=fh, timeout=600)
        return self._chk(r)

    def aspetta_pronto(self, container_id, max_sec=600, ogni=15):
        t0 = time.time()
        while True:
            st = self.get(container_id, fields="status_code,status")
            code = st.get("status_code")
            if code == "FINISHED":
                return st
            if code in ("ERROR", "EXPIRED"):
                raise ErroreAPI(f"elaborazione video fallita: {st}")
            if time.time() - t0 > max_sec:
                raise ErroreAPI(f"elaborazione troppo lunga (ultimo stato: {st})")
            time.sleep(ogni)

    def pubblica(self, ig_user_id, container_id):
        return self.post(f"{ig_user_id}/media_publish", creation_id=container_id)["id"]


# ---------------------------------------------------------------- scelta audio
def scegli_audio(meta, acc, durata_video, stato, ricerca_post=None, rng=random):
    """Audio di tendenza (o dalle parole chiave) abbastanza lungo e non usato di recente."""
    a = acc.get("audio", {}) or {}
    tipo = a.get("tipo", "music")
    parole = [ricerca_post] if ricerca_post else (a.get("ricerca") or [None])
    evita = set(stato.get("audio_usati", [])[-int(a.get("no_ripetere_ultimi", 10)):])
    vietati = set(map(str, a.get("vietati", [])))
    candidati, visti = [], set()
    for q in parole:
        for x in meta.cerca_audio(acc["ig_user_id"], tipo, q):
            aid = str(x.get("audio_id") or x.get("id") or "")
            if not aid or aid in visti or aid in vietati:
                continue
            visti.add(aid)
            candidati.append(x)
    if not candidati:
        return None, "nessun audio restituito dall'API"
    dur_ok = [x for x in candidati if (x.get("duration_in_ms") or 0) / 1000 >= durata_video]
    freschi = [x for x in dur_ok if str(x.get("audio_id") or x.get("id")) not in evita]
    pool = freschi or dur_ok or candidati
    scelto = rng.choice(pool[: int(a.get("tra_i_primi", 5))])  # i primi = più di tendenza
    return scelto, f"{len(candidati)} trovati, {len(dur_ok)} di durata ok, {len(freschi)} non usati di recente"


def descrivi_audio(x):
    if not x:
        return "-"
    t = x.get("title") or "?"
    art = x.get("display_artist") or x.get("ig_username") or ""
    return f"{t} — {art}".strip(" —")

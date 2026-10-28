"""Scarica l'audio dei reel elencati in pagine/<pagina>/audio/link.txt (gira su GitHub Actions).
Esito in pagine/<pagina>/audio/esito.txt."""
import re, subprocess, sys
from pathlib import Path

nome = sys.argv[1]
cart = Path(__file__).parent / "pagine" / nome / "audio"
righe = []
for url in (cart / "link.txt").read_text().split():
    m = re.search(r"/(?:reel|reels|p)/([\w-]+)", url)
    if not m:
        continue
    sc = m.group(1)
    dst = cart / f"{sc}.m4a"
    if dst.exists():
        righe.append(f"OK (già presente) {sc}")
        continue
    r = subprocess.run(["yt-dlp", "-q", "--no-warnings", "-f", "bestaudio/best", "-x", "--audio-format", "m4a",
                        "-o", str(cart / f"{sc}.%(ext)s"), f"https://www.instagram.com/reel/{sc}/"],
                       capture_output=True, text=True, timeout=180)
    if dst.exists():
        d = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(dst)],
                           capture_output=True, text=True).stdout.strip()
        righe.append(f"OK {sc} {float(d):.1f}s")
    else:
        righe.append(f"FALLITO {sc}: {(r.stderr or r.stdout).strip()[-300:]}")
(cart / "esito.txt").write_text("\n".join(righe) + "\n")
print("\n".join(righe))

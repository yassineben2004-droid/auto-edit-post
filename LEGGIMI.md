# Auto Edit & Post — piattaforma di pubblicazione

Pubblica da sola i Reel su più pagine Instagram, ognuna con i suoi **orari fissi**,
scegliendo ogni volta un **audio di tendenza**. A ogni orario esce il prossimo video della coda di quella pagina.

```
piattaforma.yaml              impostazioni generali (fuso, tolleranza ritardi)
PANNELLO.md                   riepilogo di tutte le pagine (si aggiorna da solo)
pagine/
  pijamamania/
    pagina.yaml               ID account, ORARI, hashtag, caption, regole audio
    coda/                     video in attesa + coda.csv (ordine di uscita e caption)
    stato.json                storico: pubblicati, mancati, coda vuota, audio usati, errori
  donidinatale/ ...
```

## Il pannello (PANNELLO.md)
Per ogni pagina: stato, orari di oggi, post al giorno, **video in coda e per quanti giorni bastano**,
prossimo turno, ultimo esito, totale della settimana. Sotto: avvisi ("coda quasi finita", errori) e gli ultimi post con link.
Su GitHub si apre direttamente dal repository, anche dal telefono.

## Comandi
| Cosa | Comando |
|---|---|
| Nuova pagina | `python piattaforma.py nuova ciabattepazze "Ciabatte Pazze"` |
| Mettere video in coda | `python piattaforma.py aggiungi pijamamania <cartella video> [<altra cartella>] --testi testi.txt` |
| Aggiornare gli orari di GitHub dopo aver cambiato orari/pagine | `python piattaforma.py cron` |
| Vedere il pannello | `python piattaforma.py pannello` |
| Prova senza pubblicare | `python piattaforma.py esegui --prova` |
| Controllare token/account/quota | `python piattaforma.py verifica` |
| Inserire l'audio vero nei video in coda (da pagine/<pagina>/audio/) | `python piattaforma.py metti-audio pijamamania` |
| Rifare i video in coda dai reel rimontati (stesso audio) | `python piattaforma.py metti-audio pijamamania --rinnova` |
| Diagnostica di un post | `python piattaforma.py info pijamamania <media_id>` |
| Vedere gli audio disponibili | `python piattaforma.py audio pijamamania natale christmas` |

Gli stessi comandi si lanciano dal sito: GitHub → **Actions → Pubblica Reel → Run workflow** → scrivi il comando.

## Orari (pagine/<pagina>/pagina.yaml)
```yaml
orari:
  ogni_giorno: ["08:15", "12:45", "18:30", "21:00"]
  sabato: ["10:00", "20:00"]        # opzionale: sostituisce ogni_giorno quel giorno
```
Dopo una modifica: `python piattaforma.py cron` (rigenera gli avvii di GitHub, già validi sia con ora solare che legale).

## Regole automatiche
- un solo post per pagina a ogni turno; se più turni sono arretrati esce solo il più recente (mai due Reel attaccati)
- un turno può uscire fino a 2 ore dopo l'orario (GitHub a volte ritarda); oltre → "mancato", il video resta in coda
- **sveglia** (`.github/workflows/sveglia.yml`): dorme fino al prossimo turno e avvia "Pubblica Reel" all'orario esatto; ogni pubblicazione la riaccende. cron-job.org e gli orari di GitHub restano come riserva
- **commit firmati dal bot**: con il repo pubblico GitHub mette "in attesa di approvazione" le esecuzioni se l'ultimo commit su main è di un autore esterno (es. "Claude"). Ogni commit su main va firmato `auto-edit-post <auto-edit-post@users.noreply.github.com>` (vedi CLAUDE.md)
- guasto temporaneo di Meta → riprova finché il turno è valido
- video rifiutato da Instagram → scartato (scritto in stato.json), al turno esce il successivo
- coda vuota → il turno è segnato "coda_vuota" e il pannello avvisa
- audio: dentro ogni video c'è un audio vero (cartella audio/ a rotazione, mai lo stesso due volte di fila), così il reel non esce mai muto; in più si prova ad agganciare la musica di tendenza (Meta a volte la ignora)
- musica di tendenza: tendenza (o parole chiave), scarta quelli più corti del video, non ripete gli ultimi 10

## Attivazione (una volta sola)
1. **App Meta**: developers.facebook.com → Crea app (caso d'uso Instagram / tipo Business). Può restare in modalità Sviluppo.
2. **Token**: consigliato un **utente di sistema** in Meta Business Suite (Impostazioni → Utenti di sistema) con
   tutte le Pagine e gli account Instagram assegnati, permessi `instagram_basic`, `instagram_content_publish`,
   `pages_show_list`, `pages_read_engagement`, `business_management`, scadenza **Mai** → un solo token per tutte le pagine.
3. **ID Instagram** di ogni pagina: Graph API Explorer → `me/accounts?fields=name,instagram_business_account` → l'`id` va in `pagina.yaml`.
4. **GitHub**: repository privato con questi file → Settings → Secrets → Actions. Due token: `TOKEN_META` (portafoglio di PijamaMania) e `TOKEN_META_STORE` (portafoglio del profilo personale, per tutti gli altri store). Ogni pagina sceglie il suo con `token_env`. Il comando `account` elenca Pagine e ID Instagram visti da ciascun token.
5. In `pagina.yaml` metti `attiva: true`, poi `python piattaforma.py cron`, commit e push.
6. Prova da Actions: `verifica`, poi `audio pijamamania natale`, poi `esegui --prova`.

## Quando le pagine diventano tante
Su GitHub gratuito (repository privato) ci sono circa 2.000 minuti al mese: ogni avvio ne consuma almeno 1.
Con molte pagine e orari diversi conviene un piccolo server sempre acceso (pochi euro al mese):
stesso codice, si lancia `python piattaforma.py esegui` ogni 5 minuti con cron.

## Testo stile TikTok + emoji iOS (monta.py)
- Il testo dei reel usa **TikTok Sans SemiBold** (il font del testo nativo di TikTok, open source, in `fonts/`):
  bianco, bordino scuro sottile e ombra morbida.
- **Rotazione 60/40** su tutti i reel con testo: 6 su 10 in TikTok Sans **SemiBold** (`tiktok`, il predefinito),
  4 su 10 in TikTok Sans **Regular**, non grassetto (`tiktok_regular`, in test). Lo stile di ogni reel finisce in
  `clip_montate/<pagina>/stili.csv`, così negli insights si confrontano i due stili.
  Per forzarne uno: `stile: tiktok` / `stile: tiktok_regular` / `stile: classico` (vecchio stile) nella ricetta.
- Un'emoji non va mai a capo da sola: resta attaccata all'ultima parola.
- Le **emoji iOS** ci sono solo montando su Mac: workflow **Monta reel** (runner macOS, font Apple Color Emoji del sistema).
  Parte da solo quando cambia un `pagine/<pagina>/ricette.yaml` (monta solo i reel nuovi) oppure
  Actions → Monta reel → Run workflow → `capybounce cb01` per rimontare.
- In ricetta: `posizione` accetta anche un numero (0.56 = 56% dall'alto); `cta_posizione: 0.20` fa sì che la CTA
  **sostituisca** l'hook negli ultimi `cta_secondi` e vada a quell'altezza (sopra le parti sgranate).
- Su Linux (montaggio locale) le emoji sono quelle Google: vanno bene solo come anteprima.

## Testo sopra le parti sgranate (clip_originali/<pagina>/sgranature.yaml)
Nelle clip prese da altri video (scritte tolte, emoji residue, strisce sfocate) il testo del reel va SEMPRE sopra
quelle parti, per coprirle.
- In `clip_originali/<pagina>/sgranature.yaml` c'è, per ogni clip, dove sta la parte sgranata (`y` = altezza,
  `altezza`, `larghezza`, `da`/`a` in secondi della clip) e se si vede molto (`forte: true`).
- `monta.py` sposta da solo il testo lì sopra (vince su `posizione`), solo nei momenti del reel in cui quella clip
  è a schermo. Parte sottile → la copre la prima riga del testo (mai lo spazio tra due righe).
- **`forte: true` → testo evidenziato**: riquadro bianco arrotondato con scritta nera, largo almeno quanto la parte
  da coprire. Scritte ed emoji residue sono sempre `forte` (col testo normale spuntano fra le parole).
  In `stili.csv` quei reel risultano `tiktok+evidenziato`.
- Per un reel che non deve spostarsi: `copri_sgranature: false` nella ricetta.
- **Clip nuove**: `python controlla_clip.py <pagina> [inizio nome]` crea in `analisi/sgranature/<pagina>/`
  (non salvati nel repo) un foglio per clip con 8 fotogrammi e la griglia delle altezze ogni 5%: da lì si leggono
  y e spessore da scrivere in sgranature.yaml. Le clip fatte su Higgsfield non hanno sgranature.
- Dopo aver cambiato sgranature.yaml: Monta reel → Run workflow → `<pagina> <inizio nomi>` per rimontare, poi
  Pubblica Reel → Run workflow → `metti-audio <pagina> --rinnova` per rifare i video già in coda dai reel
  rimontati (stesso audio, stesso posto in coda).

## Pagine solo Facebook (Reel sulla Pagina FB)
Per i brand che girano solo su Facebook (BottiZero, Doni di Natale) in `pagina.yaml`:
```yaml
piattaforma: facebook
fb_page_id: "1234567890"     # ID della Pagina: lo stampa il comando `account`
token_env: TOKEN_META_STORE
```
- Il bot ricava da solo il **token della Pagina** dal token dell'utente di sistema e pubblica con le API
  `video_reels` (start → upload → finish PUBLISHED), poi aspetta che Facebook confermi la pubblicazione.
- **Permesso necessario in più sul token:** `pages_manage_posts` (oltre a `pages_show_list` e `pages_read_engagement`).
  Utente di sistema → Genera nuovo token → spunta anche `pages_manage_posts` → aggiorna il secret `TOKEN_META_STORE` su GitHub.
  La Pagina va assegnata all'utente di sistema con **controllo completo**.
- Audio: sui Reel Facebook la musica di tendenza da API non esiste → si usa solo l'audio inserito con `metti-audio`.
- `verifica` dice se token della Pagina e permessi sono a posto; `esegui --prova` controlla senza pubblicare.

## Libreria audio comune (audio_comuni/)
Gli audio di `audio_comuni/` valgono per **tutte le pagine italiane**: `metti-audio <pagina>` usa questi + quelli
in `pagine/<pagina>/audio/` (lì vanno solo gli audio specifici, es. `VIRALE_squalo_3M6.mp3` di PijamaMania).
Per escludere una pagina (es. quelle in inglese): `audio_inseriti: {comuni: false}` in `pagina.yaml`.
Nuovi link: si mettono in `pagine/<pagina>/audio/link.txt` → workflow **Scarica audio** → poi si spostano in `audio_comuni/`.

## Pagine Instagram che escono ANCHE su Facebook
Le API di Instagram non condividono da sole sulla Pagina Facebook collegata (l'opzione "condividi su Facebook"
vale solo per i post fatti a mano dall'app). Per farlo fare al bot, in `pagina.yaml`:
```yaml
facebook:
  attivo: true
  fb_page_id: "1385448827991605"
  orari: "tutti"                 # oppure solo alcuni turni, es. ["09:45", "13:00", "18:00", "21:00"]
```
Dopo il post Instagram, a quegli orari lo stesso video esce come Reel sulla Pagina. Serve `pages_manage_posts` sul token.
Se Facebook fallisce, il post Instagram resta valido e il pannello mostra l'avviso.

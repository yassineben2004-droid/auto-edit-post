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
4. **GitHub**: repository privato con questi file → Settings → Secrets → Actions → `TOKEN_META` = il token.
5. In `pagina.yaml` metti `attiva: true`, poi `python piattaforma.py cron`, commit e push.
6. Prova da Actions: `verifica`, poi `audio pijamamania natale`, poi `esegui --prova`.

## Quando le pagine diventano tante
Su GitHub gratuito (repository privato) ci sono circa 2.000 minuti al mese: ogni avvio ne consuma almeno 1.
Con molte pagine e orari diversi conviene un piccolo server sempre acceso (pochi euro al mese):
stesso codice, si lancia `python piattaforma.py esegui` ogni 5 minuti con cron.

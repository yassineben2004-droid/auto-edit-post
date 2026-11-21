# Istruzioni per Claude — Auto Edit & Post

## Commit: firma SEMPRE come il bot
Il repo è pubblico: se l'ultimo commit su `main` ha un autore esterno (es. `Claude <noreply@anthropic.com>`),
GitHub mette in "attesa di approvazione" tutte le esecuzioni di Pubblica Reel e Sveglia e i turni saltano.
Yasso non può approvarle ogni volta a mano.

Prima di ogni commit:

    git config user.name "auto-edit-post"
    git config user.email "auto-edit-post@users.noreply.github.com"

Nei messaggi di commit NON aggiungere trailer `Co-Authored-By: Claude <noreply@anthropic.com>`
(GitHub lo collega all'utente esterno "claude"). Va bene la riga `Claude-Session: <link>`.

## Mai modificare .github/workflows da una sessione Claude
Se un commit spinto da qui cambia un file in `.github/workflows/` (es. `python piattaforma.py cron`),
GitHub mette in "action_required" ogni esecuzione di Pubblica Reel e la pubblicazione si ferma su TUTTE le pagine
(successo il 19/11/2026, risolto ripristinando pubblica.yml). La sveglia legge già gli orari da `pagine/*/pagina.yaml`:
dopo aver cambiato orari non serve `cron`; se servono gli orari di riserva, li aggiorna Yasso dal sito GitHub.

## Parti sgranate: il testo va sempre sopra
Quando arrivano clip nuove prese da altri video (TikTok/IG, scritte tolte), prima di scrivere le ricette:
`python controlla_clip.py <pagina> <inizio nome>`, guarda i fogli in analisi/sgranature/ e segna ogni parte
sgranata / scritta / emoji residua in `clip_originali/<pagina>/sgranature.yaml` (scritte ed emoji residue = `forte: true`,
così il testo esce evidenziato). monta.py poi mette il testo lì sopra da solo. Non salvare analisi/sgranature/ nel repo.

## Testi: niente frasi su tempi di ordine/consegna
Mai più nei testi/cta frasi tipo "Ordinate alle 2 di notte, arrivate oggi" o "arrivate in 24h", "consegna lampo", "ordinato ieri, arrivato oggi":
niente storie sull'ordine o sulla velocità di spedizione (i competitor virali non le usano mai). Rimossa cp45 il 21/11/2026.

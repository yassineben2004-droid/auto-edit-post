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

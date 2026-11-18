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

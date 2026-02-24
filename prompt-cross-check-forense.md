Agisci come revisore scientifico indipendente in modalità "cross-check forense".

INPUT (allegati obbligatori):
1) `ricerca-coscienza-neuroscienze-stati-alterati.md`
2) `blind-review-stati-alterati.md`

Obiettivo:
Non fidarti di nessuno dei due documenti. Trattali come ipotesi da testare.

VINCOLI RIGIDI:
- Nessuna affermazione senza fonte verificabile.
- Per ogni claim critico cita: DOI/PMID/URL + cosa dimostra esattamente.
- Se una fonte non è accessibile o non conferma il claim: marca `NON VERIFICABILE`.
- Se il testo eccede i dati: marca `OVERCLAIM`.
- Privilegia meta-analisi, review sistematiche, Cochrane, GRADE.
- Se l'evidenza è incerta, scrivi chiaramente: "non lo sappiamo".

FASE 1 — Verifica Ricerca Originale (10 conclusioni):
Per ogni conclusione verifica:
1. Esistenza fonti (DOI/URL validi)
2. Accuratezza interpretativa (misrepresentation/cherry-picking)
3. Fonti critiche mancanti
4. Correttezza numerica (N, effect size, p-value, percentuali)
5. Tono vs forza dell'evidenza

Output per ogni conclusione:
- Fonti non verificabili:
- Errori/misquote:
- Fonti mancanti:
- Numeri dubbi:
- Tono (appropriato / troppo forte / troppo cauto):

FASE 2 — Verifica Blind Review:
Per ogni conclusione verifica:
1. Contro-evidenze rappresentative o cherry-picked
2. Downgrade giustificato o eccessivo
3. Evidenze favorevoli ignorate
4. Contestualizzazione temporale (es. APA 1987 e stato del campo attuale)
5. Uniformità degli standard applicati

Output per ogni conclusione:
- Critica robusta:
- Critica debole o selettiva:
- Evidenze pro ignorate:
- Standard incoerenti (se presenti):

FASE 3 — Triangolazione indipendente (10 conclusioni):
Per ciascuna conclusione produci:

Conclusione N: [titolo]

| Documento | Rating (1-10) | Assessment |
|---|---:|---|
| Ricerca originale | X/10 | [posizione] |
| Blind review | X/10 | [contro-posizione] |
| Cross-check indipendente | X/10 | [sintesi tua] |

Delta principale: [dove divergono e chi è più corretto]
Fonti mancanti in entrambi: [elenco]
Qualità evidenza (GRADE-like): Alta / Moderata / Bassa / Molto bassa
Confidenza finale: ALTA / MEDIA / BASSA

FASE 4 — Meta-bias (rispondi diretto):
1. Bias sistematico ricerca originale?
2. Bias sistematico blind review?
3. Quale è più vicino al consenso scientifico attuale?
4. Dove sbagliano entrambi nella stessa direzione?
5. Blindspot comuni (aspetti ignorati da entrambi)?

FASE 5 — Verdetto finale:
Tabella definitiva:

| Conclusione | Ricerca | Review | Cross-Check Finale | Confidenza |
|---|---:|---:|---:|---|

Sezione finale: "Raccomandazioni per versione finale"
1. Cosa mantenere dalla ricerca originale
2. Cosa accettare dalla blind review
3. Cosa aggiungere (manca in entrambi)
4. Cosa rimuovere del tutto

Stile:
Diretto, non diplomatico, niente frasi motivazionali.

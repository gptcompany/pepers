# Strategia di Hardening Avanzata per PePeRS

Questo documento delinea i prossimi passi per l'hardening del sistema. L'obiettivo
non è aumentare la coverage in modo cosmetico, ma migliorare la **qualità** e la
**robustezza operativa** dei test.

Priorità attuali:
1. **Edge-case e regression test guidati dai failure mode reali**
2. **Property-Based Testing** dove i parser o i normalizzatori ricevono input arbitrari
3. **Mutation Testing** solo dove dimostra valore reale

Per l'orchestratore la tecnica più redditizia si è dimostrata la prima: test
integration e unit mirati su restart, timeout, preflight e requeue.

---

## 1. Property-Based Testing con `Hypothesis`

**Obiettivo**: Verificare che l'estrattore LaTeX (`services/extractor/latex.py`) sia robusto e non generi eccezioni non gestite quando processa input arbitrari e malformati.

### Piano d'azione

1.  **Installazione**:
    *   Sarà necessario aggiungere `hypothesis` alle dipendenze di sviluppo.
    *   Comando: `uv pip install hypothesis`

2.  **Creazione del Test**:
    *   Creare un nuovo file `tests/property/test_latex_extractor_robustness.py`.
    *   Importare le funzioni necessarie da `hypothesis` (`@given`, `strategies as st`) e il nostro modulo `extract_formulas`.

3.  **Definizione della Strategia di Input**:
    *   Useremo `st.text()` per generare una vasta gamma di stringhe di testo unicode, che simuleranno il contenuto di un paper.
    *   La strategia includerà parentesi, comandi LaTeX-like, e caratteri speciali per stressare i nostri regex.

4.  **Scrittura del Test di Robustezza**:
    *   Creeremo un test che non verificherà un output specifico, ma solo la stabilità della funzione.
    *   **Esempio di codice**:
        ```python
        from hypothesis import given, strategies as st
        from services.extractor.latex import extract_formulas

        @given(text=st.text())
        def test_extract_formulas_is_always_stable(text):
            """
            Verifica che extract_formulas non crashi mai, indipendentemente dall'input.
            """
            try:
                extract_formulas(text)
            except Exception as e:
                # Possiamo opzionalmente fallire solo per eccezioni specifiche che NON ci aspettiamo
                pytest.fail(f"extract_formulas() ha generato un'eccezione inattesa: {e}")
        ```

5.  **Esecuzione**:
    *   Eseguire il nuovo test con `pytest tests/property/`. Hypothesis si occuperà di generare centinaia di esempi e di riportare solo quelli che causano un fallimento.

---

## 2. Edge-Case e Regression Testing per l'Orchestrator

**Obiettivo**: Proteggere i failure mode reali della pipeline, in particolare dopo
timeout, restart di servizio e rilanci espliciti di run terminali.

### Aree ad alta priorità

- **Resume vs requeue**:
  - i run `running` orfani possono essere ripresi al boot
  - i run `partial` o `failed` devono essere requeued come nuovi run derivati
- **Preflight dipendenze esterne**:
  - `CAS` e `RAG` devono bloccare gli stage che dipendono da loro quando sono down
- **Semantica query vs paper_id**:
  - `paper_id` -> `resume_from_current_stage`
  - `query` -> `rerun_query`
- **Audit trail**:
  - il nuovo run deve persistere `requeue_of`, `requeue_strategy`,
    `requeue_source_status`, `requeue_requested_at`,
    `requeue_source_failed_stage`

### Pattern di test raccomandati

1. **Unit test del planner**
   - `PipelineRunner.build_requeue_plan(...)`
   - rifiuto di `running` e `completed`
   - blocco dei paper già a stage terminale
   - non-regression su `rerun_query`

2. **HTTP integration test**
   - `POST /runs/requeue` con `dry_run=true`
   - mix `accepted/rejected` con `run_ids`
   - preflight failure quando dipendenze richieste sono down
   - persistenza nel DB dei metadata del run derivato

3. **Regression test su timeout e restart**
   - startup resume dei soli `running`
   - skip esplicito dei downstream dopo fallimento upstream

### Nota pratica

Per questa area, test edge-case ben scelti hanno dato più valore di `mutmut`.
Il mutation testing resta opzionale e a basso ROI finché non individua buchi
concreti che i test integration non coprono.

---

## 3. Mutation Testing con `mutmut`

**Obiettivo**: Verificare che i test unitari siano sufficientemente specifici da
rilevare bug piccoli ma critici nel codice di produzione, ma solo dopo aver
coperto i failure mode reali con test espliciti.

**Target consigliati**:
- `services/orchestrator/pipeline.py`
- `services/validator/consensus.py`

### Piano d'azione

1.  **Installazione**:
    *   Aggiungere `mutmut` alle dipendenze di sviluppo.
    *   Comando: `uv pip install mutmut`

2.  **Configurazione**:
    *   Creare un file `pyproject.toml` (o modificare quello esistente) per configurare `mutmut`. Per evitare tempi di esecuzione troppo lunghi, inizieremo testando un singolo modulo.
    *   **Configurazione attuale in `pyproject.toml`** (primo target: `pipeline.py`):
        ```toml
        [tool.mutmut]
        paths_to_mutate = "services/orchestrator/pipeline.py"
        backup = false
        runner = "uv run pytest tests/unit/test_orchestrator.py -x"
        tests_dir = "tests/unit/"
        ```
    *   Per testare `consensus.py`, eseguire manualmente:
        ```bash
        uv run mutmut run --paths-to-mutate=services/validator/consensus.py \
            --runner="uv run pytest tests/unit/test_validator.py -x"
        ```

3.  **Esecuzione**:
    *   Lanciare `mutmut` per eseguire i test contro le versioni "mutate" del codice.
    *   Comando: `mutmut run`

4.  **Analisi dei Risultati**:
    *   Visualizzare i risultati con `mutmut results`.
    *   I "mutanti sopravvissuti" (` বেঁচে থাকা মিউট্যান্ট`) indicano i punti in cui i nostri test sono deboli. Ad esempio, se `mutmut` cambia un `>` in `>=` e nessun test fallisce, significa che non abbiamo un test per quel caso limite specifico.

5.  **Azione Correttiva (Iterativa)**:
    *   Per ogni mutante sopravvissuto, analizzare il codice sorgente e il test corrispondente.
    *   Modificare il test esistente (o aggiungerne uno nuovo) per essere più specifico e "uccidere" il mutante (cioè, fare in modo che il test fallisca con il codice mutato).
    *   Eseguire di nuovo `mutmut run` per verificare che il mutante sia stato eliminato.

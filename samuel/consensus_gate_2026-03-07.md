# Consensus Gate: Samuel A. Lopes Review Pack
**Date:** 2026-03-07
**Mode:** Standby di consensus con intake strutturato
**Pattern:** Confidence-gate adattato a confronto multi-AI

## 1. Objective
Close the review loop only after both external reports are available and compared against the local raw artifacts. No final conclusion should be issued before that point.

## 2. Dispatch Packs

### 2.1 ChatGPT Pack
Send the following files:
- `samuel/prompt_chatgpt.md`
- `samuel/report_draft_gemini.md`
- `samuel/terminology_map.md`
- `samuel/BC_innovation_proposal.md`

Expected output:
- Revised Preliminary Edition
- Explicit treatment of academic synergy
- Explicit identification of logical gaps in the current future path
- TOM-based refinement of the BC proposal
- Pedagogical section in Italian

### 2.2 Claude Pack
Send the following files:
- `samuel/prompt_claude.md`
- `samuel/report_draft_gemini.md`
- `samuel/terminology_map.md`
- `samuel/BC_innovation_proposal.md`
- Access to local audit records if available

Expected output:
- Technical audit grounded in local artifacts
- Clear distinction between verified claims, inferences, and conjectures
- One novel research direction not already claimed in the Gemini draft

## 2.3 Local Validation Note
The current filesystem contains additional summary artifacts, including `final_intel_report.md`, `final_preliminary_edition.md`, and `consensus_scorecard.md`.

These files are useful as working material, but they must **not** be treated as consensus ground truth yet. At least two of them already use closure language such as `final`, `consensus`, or `clinically audited` before the external ChatGPT and Claude returns have been formally compared.

Operational rule:
- `final_intel_report.md`: treat as draft narrative, not validated consensus.
- `final_preliminary_edition.md`: treat as provisional synthesis, not final output.
- `consensus_scorecard.md`: treat as checklist, not verdict.

## 3. Decision States
- `WAITING_FOR_INPUT`: One or both external reports are missing.
- `READY_FOR_COMPARISON`: Both reports received and parsed.
- `ITERATE`: One or more reports contain unsupported claims, scope drift, or missing deliverables.
- `CONSENSUS_REACHED`: Both reports agree on the evidence standard and all major contradictions are resolved.
- `HUMAN_ESCALATION`: Contradictions remain on claims that materially affect the final conclusion.

## 4. Intake Checklist
For each incoming report, verify the following before comparison:

1. Does it separate verified findings from conjectures?
2. Does it address the Lopes/BV synergy without claiming unsupported transfer?
3. Does it identify the logical gaps in the current future path?
4. Does it use formal TOM language for the BC Porto proposal?
5. Does the pedagogical Italian remain scientifically accurate and age-appropriate?
6. Does it avoid overstating pipeline progress or validation status?

If any answer is `no`, set status to `ITERATE` for that report.

## 5. Comparison Matrix

| Topic | Gemini Draft / Local Baseline | ChatGPT | Claude | Consensus Status | Notes |
|------|-------------------------------|---------|--------|------------------|-------|
| Pipeline status | Preliminary draft overstates progress; local audit shows incomplete validation | Pending | Pending | Open | Treat local audit as control |
| Lopes/BV synergy | Plausible as hypothesis, not yet established theorem | Pending | Pending | Open | Must distinguish comparison from proof |
| UNESCO 2021 | Requires world-centric integration and indigenous symmetry | Pending | Pending | Open | Check for PHBL alignment |
| Historical Redemption | Integration of the "Apology" into the BC value proposition | Pending | Pending | Open | Audit for institutional sincerity |
| Future Path logic | Transfer, evidence, criteria, and interpretation gaps identified | Pending | Pending | Open | Reject any automatic transfer claim |
| BC TOM alignment | Proposal now framed as operating model, not lesson idea only | Pending | Pending | Open | Look for value proposition, delivery model, governance |
| Italian pedagogy | Must prefer structure-preserving transformations over vague symmetry metaphors | Pending | Pending | Open | Check scientific accuracy and readability |

## 6. Closure Criteria
Consensus can be closed only if all five conditions below are satisfied:

1. Both ChatGPT and Claude reports have been received.
2. Both reports explicitly distinguish verified claims from hypotheses.
3. No report treats the Nakayama BV result as direct proof for the Weyl-subalgebra family.
4. The BC proposal is reformulated in recognisable TOM language.
5. The pedagogical Italian is both accessible and mathematically honest.

If any condition fails, the consensus remains open.

## 7. Paste Zone
Use the sections below to paste the two external reports for side-by-side review.

### 7.1 ChatGPT Report
`[paste here]`

### 7.2 Claude Report
`[paste here]`

## 8. Final Output Rule
The final "Hard and Heavy" conclusion must be written only after Section 5 is completed and Section 6 passes in full.

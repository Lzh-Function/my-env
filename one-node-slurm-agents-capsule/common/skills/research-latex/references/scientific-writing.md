# Scientific report quality and evidence handling

## Input audit

Before drafting, enumerate relevant inputs: tables, raw files, checkpoint paths, plotting scripts, notes, DOI links, conference papers, metrics. Identify missing information. Do not infer measurements from filenames or visually estimate exact values from figures where numerical data exist.

For ML/chemical language model reports, record (when available):
- Task definition, endpoints, train/validation/test separation, leakage prevention, data cleaning and de-duplication.
- Molecular representation (SMILES canonicalization/randomization, stereochemical handling, tokenization, max length, vocabulary size); source/version/quality restrictions.
- Architecture, parameter count, initialization, seeds, optimizer, scheduler, precision, hardware allocation, step/epoch/token counts, checkpoints, software versions and Git commit.
- Primary and secondary metrics, sample count, uncertainty intervals, class balance, statistical tests and exclusions. For model comparisons, match data splits and evaluation protocols.
- In learning-dynamics analysis, distinguish *empirical phase transition / rapid metric change* from mechanistic interpretation; a probe or CKA change is evidence about a measurement, not automatic proof of causal representation reorganization.

## Recommended structures

### Academic (`academic`)

Title + authors + abstract → background and contribution → methods → experimental setup → results → discussion and limitations → conclusion → references. Supplementary appendices when appropriate.

### Technical (`technical`)

Executive summary/abstract → question → inputs/provenance → experimental settings → results (plots/tables) → interpretation → limitations → next actions → references → appendix. This is the default for frequent experiment reporting.

### Monograph (`monograph`)

Title page → preface → TOC → prerequisites → foundational concepts/definitions → derivations/propositions → methods/taxonomy → applications → limitations and open questions → references. Keep chapters modular and cross-referenced.

## Evidence contract

1. Every quantitative claim traces to a source file and computation, or is clearly labeled an estimate/assumption.
2. Never present demonstration content as a measurement or cite illustrative bibliography automatically.
3. Verbatim quotations are short and attributed; paraphrases should remain faithful.
4. Never invent DOI identifiers, author order, titles or results. Verify against papers/citable metadata where possible.
5. Distinguish **observed**, **hypothesized**, **planned** and **unavailable**.
6. Use units, dimensions, significant figures and confidence estimates appropriately.
7. State exclusions, negative results, failure modes, caveats and possible alternative explanations.
8. Keep date/time and experimental versioning explicit; do not fill placeholders silently.
9. Treat all generated figures as part of the scientific record; keep generation commands/scripts and source datasets.
10. Prevent accidental disclosure of private research datasets, credentials, or unpublished results when publishing or archiving.

## Verification before delivery

- Are the title, authorship, affiliations and date accurate?
- Do figures/tables come from real data, and are transformations auditable?
- Do axis labels define units and normalizations?
- Does each caption describe sample count, relevant experimental context and the meaning of uncertainty?
- Do plots/claims match the inputs (including baselines and versions)?
- Are citations relevant and genuinely verified?
- Are results and interpretations separated and limitations stated?
- Is enough methodology preserved for a peer to reproduce the measurements?

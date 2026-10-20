# Research audit brief

Select the questions relevant to the actual claims and include their evidence paths.

- Do the objective, implemented method and stated conclusion agree?
- Are training, validation and test separated by subject, group and time where appropriate? Inspect preprocessing, feature selection and model-selection steps for leakage.
- Do baselines receive comparable tuning budgets, datasets, compute and evaluation conditions?
- What is the independent statistical unit? Check replication, seeds, uncertainty intervals, multiple comparisons and pseudoreplication.
- Are data versions, source and input hashes, configuration, environment and artifact provenance sufficient to reproduce the reported procedure?
- Do tables, figures and metrics match supplied results? Identify unsupported causal or generalization claims and missing negative results.
- Where source papers are supplied, do citations support the associated claims? Mark inaccessible sources as unverified.

Distinguish observed defects from hypotheses. Identify whether evidence was read or independently reproduced. Static cross-review does not itself rerun training, tests or analyses; request a separate bounded validation step when that is needed.

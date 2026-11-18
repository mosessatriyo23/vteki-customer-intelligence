# Moses — Data & AI (development, synthetic)

Scope that Moses can complete independently: generator/audit, validation/ingestion dev, Identity Resolution, Customer360, RFM/lifecycle (PROPOSED), source/Golden EDA, historical features, labels/baseline/diagnostics, model card and team handoff.

Start from `TEAM_HANDOFF_2026-10-16.md`, then `independent_scope_completion.md` and `model_card_development_v1.md`.

For cross-team implementation tasks, owners, acceptance evidence and handoff steps, read [`CROSS_TEAM_IMPLEMENTATION_GUIDE.md`](CROSS_TEAM_IMPLEMENTATION_GUIDE.md). Use [`READINESS_REVIEW_PACKET_2026-11-16.md`](READINESS_REVIEW_PACKET_2026-11-16.md) for the compatibility matrix, historical acceptance scenarios, coverage inventory and Gate D template. Latest sprint/gate status: [`sprint_gate_status_2026-11-14.md`](sprint_gate_status_2026-11-14.md).

For the 2026-11-18 source-limited unblock status, independent churn decisions, Golden UUID mapping output and proposed James snapshot acceptance, read [`MOSES_UNBLOCK_HANDOFF_2026-11-18.md`](MOSES_UNBLOCK_HANDOFF_2026-11-18.md). It does not change gate status or approve training. The proposed per-target wire fields and current AIScores compatibility gaps are in [`PREDICTION_CONTRACT_I04_DRAFT_2026-11-18.md`](PREDICTION_CONTRACT_I04_DRAFT_2026-11-18.md).

For the handoff James requested (data readiness, feature validation, churn/CLV evaluation, experiment comparison, decisioning validation, and the readiness checklist with reviewer/date fields), see [`evidence/`](evidence/), starting with [`evidence/06_AI_READINESS_CHECKLIST.md`](evidence/06_AI_READINESS_CHECKLIST.md). For work packages and paste-ready prompts to Christ and James to close Gate A/C, see [`GATE_AC_CLOSURE_PLAN_2026-11-17.md`](GATE_AC_CLOSURE_PLAN_2026-11-17.md). For independent, dependency-free work completed while Gates A–C remain open, see [`RETENTION_METHOD_PROPOSAL_2026-11-17.md`](RETENTION_METHOD_PROPOSAL_2026-11-17.md), [`CANDIDATE_EVALUATION_PLAN_2026-11-17.md`](CANDIDATE_EVALUATION_PLAN_2026-11-17.md), and [`REASON_CODE_EVIDENCE_DESIGN_2026-11-17.md`](REASON_CODE_EVIDENCE_DESIGN_2026-11-17.md) — all plans/designs with no training, results, or new approvals. For Moses's concrete review and proposed data handoff to James plus unanswered decisions for Christ, see [`MOSES_REVIEW_JAMES_HANDOFF_2026-11-17.md`](MOSES_REVIEW_JAMES_HANDOFF_2026-11-17.md).

Do not treat these as production model evidence. Ground truth stays evaluation-only. `training_ready=false` and `experiment_ready=false` until platform/history/business contracts change.

# Proposed reason-code evidence contract (design only)

**Status:** DRAFT / NOT RUN — 17 November 2026. No candidate model, SHAP output, or approved explanation taxonomy exists. Requirement baseline: `docs/christ_business/reference/Requirement_Capstone.md`; consumer shape: `services/decision/nba/engine.py::AIScores.reason_codes` (minimum three described, not enforced by the consumer).

## Proposed handoff

For each as-of customer score, carry (1) stable `reason_code` identifier, (2) feature name and **version**, (3) feature value and unit, (4) feature `effective_at`/`known_at` and source/coverage marker, (5) explanation direction and evidence method/version, (6) customer ID, score ID, and cutoff. A display message may be generated only from an approved, localized template; it is **not** itself evidence. No reason may use `ground_truth`, post-cutoff observations, mutable current-state fields presented as historical facts, or unapproved business thresholds. Explanations must be faithful to the actual score producer; a hypothetical feature name is not evidence of model influence.

Suggested schema example (**structural illustration, not a generated reason**):

```text
score_id | customer_id | cutoff | reason_code | feature_version | feature_value
feature_effective_at | feature_known_at | source_coverage | method_version | display_template_version
```

## Validation before publication

- Validate unique nonempty identifiers and traceable, eligible features with `feature_known_at <= cutoff`; compare feature snapshot to the immutable score snapshot and reconcile missingness.
- Require three **distinct, substantiated** reasons only when a model/explanation method can actually produce them. If fewer than three: mark `INSUFFICIENT_EXPLANATION`, block this proposed handoff, and request review; never duplicate or fabricate a third reason. Development-only `validate_score_handoff()` checks identifier count and shape, **not** feature provenance or explanation faithfulness.
- Check calibrated band mapping and CLV tier against the approved version *once available*. A known enum alone cannot prove consistency; thresholds and lifecycle priority remain review dependencies.
- Separate factual explanation from suggested action; reasons are not permission to contact a customer. Any nudge remains a draft subject to human approval and consent/suppression checks.

**Gate status:** `training_ready=false`, `experiment_ready=false`, `final_model=false`. This design makes no claim of completeness, local explanations, or production suitability.

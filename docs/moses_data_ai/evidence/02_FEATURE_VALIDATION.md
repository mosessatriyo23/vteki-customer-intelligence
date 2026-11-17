# 02 — Feature validation, leakage checks (development only)

**Date:** 2026-11-17. **Scope:** event-time feature pipeline, `services/data/features/snapshot.py`, `VERSION="event-time-dev-1.0"`. **Owner:** Moses. **Reviewer:** pending. **Approval date:** not granted.

```text
training_ready=false
experiment_ready=false
final_model=false
```

## What is proven

`tests/data/test_pit_features.py` checks cutoff validation, window boundary correctness, deduplication and future-row exclusion at event time, and that the CLI output/manifest rejects a mutated future row.

`tests/data/test_data_leakage.py` (added in Moses PR #38) injects a valid, checksummed synthetic transaction one day (T+1) and two days (T+2) after a fixed cutoff, revalidates the batch, and asserts:

- feature CSV output and the recency-rule baseline prediction at the cutoff are **byte-identical/unchanged** before and after the future injection;
- the injected transaction is correctly counted once its own event time is reached (positive control, not a vacuous pass).

Targeted reproduction command:

```powershell
python -m unittest tests.data.test_data_leakage tests.data.test_pit_features
```

Both included in the historical broader 54-test run reported in `01_DATA_READINESS.md`; all passed then, not rerun for this refresh. PR #38 is now merged with successful final-head and merge-commit CI; see the [2026-11-17 CI refresh](06_AI_READINESS_CHECKLIST.md#ci-evidence-refresh--2026-11-17-github-cli-not-approval). This does not expand the event-time-only scope.

## What is not proven

The feature pipeline docstring explicitly states it is **event-time only, not availability-time safe**. The synthetic source CSVs carry no `available_at` field, so the leakage checks above cannot certify that `available_at > known_at` exclusion holds; that requires James's bitemporal transaction/visit/renewal history plus a feature snapshot built from his ledger (`project_transaction_as_of`, `get_business_events_as_of`), which `build_profiles_as_of()` does not yet feed into Customer360 aggregates. Do not present this report as bitemporal leakage certification.

No new feature version, no feature selection against a trained model, and no SHAP/explainability output exists in this checkout.

## Required for a stronger claim

1. James: ledger-backed, availability-aware Customer360/feature aggregation, with acceptance evidence per `../READINESS_REVIEW_PACKET_2026-11-16.md` scenarios J-A–J-D.
2. Christ: approved feature inputs consistent with the final target/CLV/lifecycle contract (no change proposed here).
3. Moses: re-run an equivalent late-arriving-event test against the ledger-backed pipeline once available, and version any new feature contract rather than overwrite the current one.

**Disposition:** existing event-time feature pipeline and baseline are unchanged by injected future events, as far as the described synthetic source permits testing. No bitemporal or production claim is made. **Reviewer pending; approval date not granted.**

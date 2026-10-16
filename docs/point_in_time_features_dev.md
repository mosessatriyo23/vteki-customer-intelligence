# Historical feature snapshots — development contract

This stage creates repeatable event-time feature rows for one or more cutoffs. It is a
leakage-testing foundation, **not training-ready point-in-time data**.

## Contract

Each `(golden_customer_id, cutoff_at)` row contains only transactions whose business
event time is at or before the inclusive cutoff. Cutoffs must be unique and use `+07:00`.
Windows use `(cutoff - N days, cutoff]`: the exact lower boundary is excluded.

Features v`event-time-dev-1.0`:

- recency and tenure in calendar days;
- deduplicated qualifying purchase counts over 60, 90 and 365 days;
- retained revenue over 90 and 365 days;
- identity status and explicit identity-time policy.

Only `COMPLETED`/`PARTIAL_REFUND` transactions are eligible. The existing conservative
business fingerprint removes known source replays. Missing customer references remain
unattributed. Ground truth is never read.

Every row declares:

```text
training_ready=False
identity_time_policy=CURRENT_SNAPSHOT_RETROSPECTIVE
```

## Why this is not yet true PIT training data

Event time alone is insufficient for production ML. The source does not record when each
row or correction became available to the platform. A transaction before a historical
cutoff may have been ingested later, while current status/refund values may include later
knowledge. Current resolver clusters are also applied retrospectively; registry versions
and effective dates do not exist yet. Therefore these rows must not be used to claim a
leakage-free trained model.

James's persistent identity registry and ingestion metadata should eventually supply:
`available_at`, immutable source versions, batch ID, registry version/effective period,
and review decision time. Refund events need their own timestamps or versions.

## Publication safeguards

The CLI validates the complete inbound batch, validates resolver checksums through the
existing snapshot builders, records input/output hashes, rejects duplicate cutoffs and
existing output directories, and writes the manifest last as the completion marker.
A directory without `feature_manifest.json` is incomplete and must not be consumed.
Publication is not transactionally atomic across files; PostgreSQL/object-store promotion
remains future work.

Run from WSL with a new output directory:

```bash
python3 -m services.data.features.cli \
  --inbound inbound/2026-09-06 \
  --resolution artifacts/identity/v11 \
  --cutoff-at 2026-03-01T23:59:59+07:00 \
  --cutoff-at 2026-06-01T23:59:59+07:00 \
  --cutoff-at 2026-09-06T23:59:59+07:00 \
  --output-dir artifacts/features/event-time-dev-run1
```

Do not choose cutoffs whose label horizon extends beyond observed data. Labels remain a
separate future-window contract and must never be columns in this feature output.

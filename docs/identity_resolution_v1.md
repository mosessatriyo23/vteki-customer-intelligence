# Identity Resolution baseline v1 (PROPOSED)

Source-only heuristic implementation, not a calibrated probabilistic model.

## Implementation

`services/data/identity/resolver.py` normalizes names (NFKC/case/whitespace), Indonesian
phone formatting and email case/whitespace. Raw fields are never overwritten on disk.
Email dots/plus aliases are NOT globally stripped: those transformations are provider
specific and could merge different real identities. Identifier blocking reduces all-pair
comparisons. Oversized blocks (>200) are explicitly reported and not expanded.

AUTO_MATCH requires >=2 matching identifiers (phone/email/member), name similarity >=.75,
and matching nonempty birth month/gender; conflicting member codes prohibit merges.
A single matching identifier cannot auto-merge. Identifier conflicts and insufficient
corroboration produce KEEP_SEPARATE or REVIEW. Heuristic .95/.60 scores are not calibrated
confidence probabilities, and are not approval of the proposed .92/.60 business thresholds.
Complete-link cluster checks prevent transitive bridges from bypassing pair evidence.

`mapping.csv`: source_customer_id, golden_customer_id, resolver_version.
`decisions.csv`: left_source_id, right_source_id, decision, heuristic_score, reason.
`oversized_blocks.json`: skipped blocks needing review.

Golden IDs are UUIDv5 of the cluster's lexicographic source anchor. They are reproducible
for the same input regardless of row order, but NOT a persistent incremental registry:
newly arriving lower source IDs can change an anchor. Persistence/versioned merge-unmerge
and explicit review queue resolution are outstanding. Singleton IDs are provisional.

## Run (WSL)

```bash
python3 -m services.data.identity.cli --source inbound/2026-09-06/crm_customers.csv --output-dir artifacts/identity/v1
python3 generator/evaluate_identity.py --predicted artifacts/identity/v1/mapping.csv --truth generator/ground_truth/identity_mapping.csv
python3 -m unittest -v tests.data.test_identity_resolution
```

Evaluation is separate under generator; resolver has no truth input parameter or imports.
Synthetic golden UUIDs and predicted UUIDs need not match: evaluation compares partitions,
not literal IDs. Output includes pair precision/recall, false positive/negative pairs and
mixed-truth clusters. Source coverage mismatch causes explicit rejection.

## Executed benchmark

- 2000 golden/2440 source: 2055 predicted clusters, 487 candidates; precision 1.0,
  recall .859470, 0 false-merge clusters, 69 missed duplicate pairs.
- 50000 golden/61000 source: 51478 predicted clusters, 12263 candidates; precision 1.0,
  recall .858952, 0 false-merge clusters, 1715 missed duplicate pairs.

These results validate the conservative baseline on THIS generator, not accuracy on real
customers. Identifier uniqueness in synthetic data makes matching easier than production.
Mapping completeness is 100% (including singleton sources) but is NOT duplicate recall.
The suggested >=95% target needs a precise agreed metric and has not been claimed met.

## Next gates

Improve candidate recall and review handling without single-attribute merges; test adversarial
collisions, contradictory demographic evidence and incremental updates; persist cluster registry
and audit decisions; coordinate PostgreSQL tables with James. No Customer360 or model training
is declared complete. No campaign/NBA implementation is introduced here.

"""Evaluation-only: compare predicted partitions to synthetic truth, label-invariant."""
import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path


def read(path):
    with Path(path).open(newline='', encoding='utf-8') as stream:
        rows = list(csv.DictReader(stream))
    mapping = {r['source_customer_id']: r['golden_customer_id'] for r in rows}
    if len(mapping) != len(rows):
        raise ValueError('Duplicate source ID')
    return mapping


def evaluate(predicted, truth):
    if not predicted or not truth:
        raise ValueError('Mappings must be nonempty')
    if set(predicted) != set(truth):
        raise ValueError('Source coverage mismatch')
    contingency = Counter((predicted[key], truth[key]) for key in truth)
    predicted_sizes = Counter(predicted.values())
    truth_sizes = Counter(truth.values())
    pairs = lambda n: n * (n - 1) // 2
    true_positive = sum(pairs(n) for n in contingency.values())
    predicted_pairs = sum(pairs(n) for n in predicted_sizes.values())
    true_pairs = sum(pairs(n) for n in truth_sizes.values())
    owners = defaultdict(set)
    for key in truth:
        owners[predicted[key]].add(truth[key])
    return {'source_count': len(truth), 'predicted_clusters': len(predicted_sizes),
            'true_clusters': len(truth_sizes), 'false_merge_clusters': sum(len(v) > 1 for v in owners.values()),
            'pair_precision': true_positive / predicted_pairs if predicted_pairs else None,
            'pair_recall': true_positive / true_pairs if true_pairs else None,
            'false_positive_pairs': predicted_pairs - true_positive,
            'false_negative_pairs': true_pairs - true_positive}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--predicted', type=Path, required=True)
    parser.add_argument('--truth', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(evaluate(read(args.predicted), read(args.truth)), indent=2))

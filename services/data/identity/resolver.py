"""Conservative source-only identity baseline; heuristic scores, not probabilities."""
from __future__ import annotations

import csv
import re
import unicodedata
import uuid
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path

VERSION = 'identity-baseline-1.1'
# Explicit fixture-only alias policy; never apply globally to real mail providers.
SYNTHETIC_ALIAS_DOMAINS = frozenset({'example.id', 'mail.id', 'inbox.id', 'customer.test'})
NAMESPACE = uuid.UUID('29e99bbb-e5bd-43c6-b67a-47bc7e6ee937')


def normalize_name(value: str) -> str:
    return ' '.join(re.sub(r'[^\w\s]', ' ', unicodedata.normalize('NFKC', value).casefold()).split())


def normalize_phone(value: str) -> str:
    digits = re.sub(r'\D', '', value)
    if digits.startswith('0'):
        digits = '62' + digits[1:]
    return digits if digits.startswith('62') and 10 <= len(digits) <= 15 else ''


def normalize_email(value: str) -> str:
    # Do not strip dots or +tags globally: provider-dependent transformations can merge strangers.
    value = value.strip().casefold()
    return value if value.count('@') == 1 else ''


def email_match_key(value: str, synthetic_aliases: bool = False) -> str:
    email = normalize_email(value)
    if synthetic_aliases and email:
        local, domain = email.split('@')
        if domain in SYNTHETIC_ALIAS_DOMAINS:
            local = re.sub(r'\+src[0-9]+$', '', local)
            email = local + '@' + domain
    return email


def normalize(row: dict, synthetic_aliases: bool = False) -> dict:
    return {**row, 'name': normalize_name(row.get('full_name', '')),
            'phone': normalize_phone(row.get('phone_raw', '')),
            'email': email_match_key(row.get('email_raw', ''), synthetic_aliases),
            'member': row.get('member_code', '').strip().upper()}


def evidence(a: dict, b: dict) -> tuple[str, float, str]:
    matches = [key for key in ('phone', 'email', 'member') if a[key] and a[key] == b[key]]
    conflicts = [key for key in ('email', 'member') if a[key] and b[key] and a[key] != b[key]]
    similar = SequenceMatcher(None, a['name'], b['name']).ratio() if a['name'] and b['name'] else 0.0
    demographic = all(a.get(key) and a.get(key) == b.get(key) for key in ('birth_month', 'gender'))
    # Email disagreement is allowed for two agreeing identifiers (cross-source variants).
    if 'member' in conflicts or (len(matches) < 2 and conflicts):
        return 'KEEP_SEPARATE', 0.0, 'identifier_conflict'
    if len(matches) >= 2 and similar >= 0.75 and demographic:
        return 'AUTO_MATCH', 0.95, '+'.join(matches) + '+name+demographics'
    if matches:
        return 'REVIEW', 0.60, '+'.join(matches) + ':insufficient_corroboration'
    return 'KEEP_SEPARATE', 0.0, 'no_identifier_support'


def resolve(rows: list[dict], max_block_size: int = 200, synthetic_aliases: bool = False) -> dict:
    if max_block_size < 2:
        raise ValueError('max_block_size must be >=2')
    records = sorted((normalize(row, synthetic_aliases) for row in rows), key=lambda row: row['crm_customer_id'])
    ids = [row['crm_customer_id'] for row in records]
    if any(not value for value in ids) or len(ids) != len(set(ids)):
        raise ValueError('Source IDs must be nonempty and unique')
    blocks = defaultdict(list)
    for i, row in enumerate(records):
        for key in ('phone', 'email', 'member'):
            if row[key]:
                blocks[(key, row[key])].append(i)
    candidates = set()
    oversized = []
    for (key, value), indices in sorted(blocks.items()):
        if len(indices) > max_block_size:
            oversized.append({'attribute': key, 'value': value, 'size': len(indices)})
            continue
        for position, left in enumerate(indices):
            for right in indices[position + 1:]:
                candidates.add((left, right))
    groups = {i: {i} for i in range(len(records))}
    owner = list(range(len(records)))
    decisions = []
    for left, right in sorted(candidates):
        decision, score, reason = evidence(records[left], records[right])
        if decision == 'AUTO_MATCH' and owner[left] != owner[right]:
            a, b = owner[left], owner[right]
            # Complete-link prevents transitive bridges bypassing contradictory evidence.
            if all(evidence(records[x], records[y])[0] == 'AUTO_MATCH' for x in groups[a] for y in groups[b]):
                for member in groups[b]:
                    owner[member] = a
                groups[a].update(groups.pop(b))
            else:
                decision, reason = 'REVIEW', 'cluster_conflict'
        decisions.append({'left_source_id': ids[left], 'right_source_id': ids[right],
                          'decision': decision, 'heuristic_score': score, 'reason': reason})
    mapping = []
    for indices in groups.values():
        anchor = min(ids[i] for i in indices)
        golden = str(uuid.uuid5(NAMESPACE, anchor))
        for i in sorted(indices):
            mapping.append({'source_customer_id': ids[i], 'golden_customer_id': golden,
                            'resolver_version': VERSION})
    return {'mapping': sorted(mapping, key=lambda row: row['source_customer_id']),
            'decisions': decisions, 'oversized_blocks': oversized}


def preserve_existing_ids(result: dict, prior_mapping: dict[str, str]) -> dict:
    """Preserve published IDs; reject conflicting merges and splits for manual review.

    A prior registry must only come from a reviewed run of this resolver. New sources
    joining one old cluster inherit its ID; all-new clusters keep their UUIDv5 ID.
    """
    if not prior_mapping or any(not source or not golden for source, golden in prior_mapping.items()):
        raise ValueError('A nonempty registry with valid source and golden IDs is required')
    current = {row['source_customer_id']: row for row in result['mapping']}
    if not set(prior_mapping) <= set(current):
        raise ValueError('Previously published source records cannot disappear')
    old_to_new: dict[str, set[str]] = defaultdict(set)
    new_to_old: dict[str, set[str]] = defaultdict(set)
    for source, golden in prior_mapping.items():
        predicted = current[source]['golden_customer_id']
        old_to_new[golden].add(predicted)
        new_to_old[predicted].add(golden)
    if any(len(parts) > 1 for parts in old_to_new.values()):
        raise ValueError('Existing cluster would split; manual review required')
    if any(len(parts) > 1 for parts in new_to_old.values()):
        raise ValueError('Two published golden IDs would merge; manual review required')
    replacements = {cluster: next(iter(owners)) for cluster, owners in new_to_old.items()}
    published = set(prior_mapping.values())
    for row in result['mapping']:
        cluster = row['golden_customer_id']
        if cluster not in replacements and cluster in published:
            raise ValueError('New cluster ID collides with published registry')
        row['golden_customer_id'] = replacements.get(cluster, cluster)
    return result


def resolve_csv(source: Path, synthetic_aliases: bool = False) -> dict:
    with source.open(newline='', encoding='utf-8') as stream:
        return resolve(list(csv.DictReader(stream)), synthetic_aliases=synthetic_aliases)

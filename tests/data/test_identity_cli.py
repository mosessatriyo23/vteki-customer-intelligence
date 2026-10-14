import csv
import json
import tempfile
import unittest
from pathlib import Path

from services.data.identity.cli import run
from services.data.ingestion.validator import sha256

FIELDS = ('crm_customer_id', 'full_name', 'phone_raw', 'email_raw', 'birth_month', 'gender',
          'city', 'member_code', 'membership_tier', 'join_date', 'preferred_branch_code',
          'status', 'source_updated_at')


def write_source(path, records):
    with path.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS, lineterminator='\n')
        writer.writeheader()
        writer.writerows(records)


def person(identity, **changes):
    row = dict(crm_customer_id=identity, full_name='Ayu Permata', phone_raw='081234567890',
               email_raw='ayu.001@example.id', birth_month='3', gender='F', city='Solo',
               member_code='M1', membership_tier='BRONZE', join_date='2025-01-01',
               preferred_branch_code='BR-01', status='ACTIVE', source_updated_at='2025-01-01T00:00:00+07:00')
    row.update(changes)
    return row


class IdentityCliTests(unittest.TestCase):
    def test_outputs_manifest_review_and_reproducibility(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = root / 'source.csv'
            write_source(source, [person('a', member_code='', membership_tier='', email_raw=''),
                                  person('b', member_code='', membership_tier='', email_raw='')])
            first, second = root / 'one', root / 'two'
            result = run(source, first)
            run(source, second)
            self.assertEqual(result['review_pairs'], 1)
            self.assertEqual((first / 'mapping.csv').read_bytes(), (second / 'mapping.csv').read_bytes())
            with (first / 'review_queue.csv').open(newline='', encoding='utf-8') as stream:
                self.assertEqual(len(list(csv.DictReader(stream))), 1)
            manifest = json.loads((first / 'resolution_manifest.json').read_text())
            self.assertEqual(manifest['source_sha256'], sha256(source))
            for name, digest in manifest['output_sha256'].items():
                self.assertEqual(digest, sha256(first / name))
            with self.assertRaisesRegex(ValueError, 'must not be overwritten'):
                run(source, first)

    def test_prior_schema_rejects_truth_and_preserves_published_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = root / 'source.csv'; prior = root / 'prior.csv'
            write_source(source, [person('a'), person('z')])
            prior.write_text('source_customer_id,golden_customer_id,resolver_version\nz,published,id-v1\n', encoding='utf-8')
            run(source, root / 'output', prior_mapping=prior)
            with (root / 'output/mapping.csv').open(newline='', encoding='utf-8') as stream:
                mapping = list(csv.DictReader(stream))
            self.assertEqual({r['golden_customer_id'] for r in mapping}, {'published'})
            truth = root / 'truth.csv'
            truth.write_text('source_customer_id,golden_customer_id,source_system,identity_scenario\nz,secret,CRM,GOLDEN_SOURCE\n', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'not ground truth'):
                run(source, root / 'rejected', prior_mapping=truth)

    def test_failed_registry_merge_leaves_no_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = root / 'source.csv'; prior = root / 'prior.csv'
            write_source(source, [person('a'), person('b')])
            prior.write_text('source_customer_id,golden_customer_id,resolver_version\na,old-a,v1\nb,old-b,v1\n', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'would merge'):
                run(source, root / 'rejected', prior_mapping=prior)
            self.assertFalse((root / 'rejected').exists())
            self.assertIn('old-a', prior.read_text())

    def test_output_cannot_contain_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = root / 'inside/source.csv'
            source.parent.mkdir(); write_source(source, [person('a')])
            with self.assertRaisesRegex(ValueError, 'must not contain'):
                run(source, root / 'inside')


if __name__ == '__main__':
    unittest.main()

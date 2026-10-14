import unittest
from services.data.identity.resolver import resolve, normalize_phone, normalize_email, preserve_existing_ids


def person(identity, **changes):
    return {'crm_customer_id': identity, 'full_name': 'Ayu Permata', 'phone_raw': '081234567890',
            'email_raw': 'ayu@example.test', 'member_code': 'M1', 'birth_month': '3', 'gender': 'F', **changes}


class IdentityTests(unittest.TestCase):
    def test_normalization_and_reproducibility(self):
        self.assertEqual(normalize_phone('+62 812-3456-7890'), normalize_phone('081234567890'))
        self.assertNotEqual(normalize_email('a+b@example.test'), normalize_email('a@example.test'))
        rows = [person('b', full_name='Ayu Permta'), person('a')]
        first = resolve(rows)
        self.assertEqual(first, resolve(list(reversed(rows))))
        self.assertEqual(len({r['golden_customer_id'] for r in first['mapping']}), 1)

    def test_shared_phone_never_merges_strangers(self):
        rows = [person('a'), person('b', email_raw='other@example.test', member_code='M2')]
        result = resolve(rows)
        self.assertEqual(len({r['golden_customer_id'] for r in result['mapping']}), 2)
        self.assertEqual(result['decisions'][0]['decision'], 'KEEP_SEPARATE')

    def test_single_identifier_review_and_transitive_bridge(self):
        result = resolve([person('a', member_code='', email_raw=''), person('b', member_code='', email_raw='')])
        self.assertEqual(result['decisions'][0]['decision'], 'REVIEW')
        self.assertEqual(len({r['golden_customer_id'] for r in result['mapping']}), 2)
        rows = [person('a', member_code='M1', email_raw='one@test'),
                person('b', member_code='M1', email_raw='shared@test'),
                person('c', member_code='', email_raw='shared@test')]
        mapping = {r['source_customer_id']: r['golden_customer_id'] for r in resolve(rows)['mapping']}
        self.assertEqual(mapping['a'], mapping['b'])
        self.assertNotEqual(mapping['a'], mapping['c'])

    def test_allowlisted_synthetic_alias_opt_in(self):
        a = person('a', phone_raw='081234567890', email_raw='ayu.000001@example.id', member_code='')
        b = person('b', phone_raw='081234567890', email_raw='ayu.000001+src2@example.id', member_code='')
        self.assertEqual(len({r['golden_customer_id'] for r in resolve([a, b])['mapping']}), 2)
        self.assertEqual(len({r['golden_customer_id'] for r in resolve([a, b], synthetic_aliases=True)['mapping']}), 1)
        c = person('c', phone_raw='081234567890', email_raw='ayu+src2@gmail.com', member_code='')
        d = person('d', phone_raw='081234567890', email_raw='ayu@gmail.com', member_code='')
        self.assertEqual(len({r['golden_customer_id'] for r in resolve([c, d], synthetic_aliases=True)['mapping']}), 2)

    def test_registry_preserves_ids_and_rejects_merges_and_splits(self):
        old = resolve([person('z')])
        golden = old['mapping'][0]['golden_customer_id']
        incoming = resolve([person('a'), person('z')])
        preserved = preserve_existing_ids(incoming, {'z': golden})
        self.assertEqual({r['golden_customer_id'] for r in preserved['mapping']}, {golden})
        with self.assertRaisesRegex(ValueError, 'published golden IDs would merge'):
            preserve_existing_ids(resolve([person('a'), person('z')]), {'a': 'published-a', 'z': 'published-z'})
        with self.assertRaisesRegex(ValueError, 'cluster would split'):
            preserve_existing_ids(resolve([person('a', email_raw='a@test', member_code='A'),
                                           person('z', email_raw='z@test', member_code='Z')]),
                                  {'a': golden, 'z': golden})

    def test_large_blocks_and_duplicate_ids(self):
        result = resolve([person(str(i), member_code='', email_raw='') for i in range(4)], max_block_size=2)
        self.assertEqual(len(result['oversized_blocks']), 1)
        self.assertEqual(len(result['mapping']), 4)
        with self.assertRaises(ValueError):
            resolve([person('a'), person('a')])

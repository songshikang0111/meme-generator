"""Behavioral checks against curated cards; no network, keys or model downloads."""
import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import numpy as np

import meme


class LibraryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = meme.ROOT / 'catalog'

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.library = Path(self.temp.name) / 'catalog'
        (self.library / 'cards').mkdir(parents=True)
        shutil.copy(self.source / 'concepts.json', self.library / 'concepts.json')
        for path in (self.source / 'cards').glob('*.json'):
            card = meme.read_json(path)
            if card['status'] == 'ready':
                meme.atomic_json(self.library / 'cards' / path.name, card)
        meme.build(self.library)

    def tearDown(self):
        self.temp.cleanup()

    def test_scenario_retrieval_and_no_directory_traversal(self):
        cases = [
            ('burning room and calm dog', '55311130'),
            ('two red buttons and a sweating person', '87743020'),
            ('cyclist puts a stick in his own wheel', '79132341'),
            ('employee thrown out of a meeting window', '1035805'),
            ('two products are the same picture', '180190441'),
        ]
        with patch.object(Path, 'glob', side_effect=AssertionError('search must not walk cards')):
            for query, expected in cases:
                with self.subTest(query=query):
                    result = meme.search(self.library, query, 5, mode='lexical')
                    self.assertIn('imgflip-' + expected, [r['id'] for r in result['results']])
        self.assertEqual(meme.search(self.library, 'quantumquokkanotincatalog')['results'], [])

    def test_incremental_put_delete_rebuild_and_draft_exclusion(self):
        card = meme.get_card(self.library, 'imgflip-181913649')
        card['id'] = 'local-new-example'
        card['name'] = 'quantumquokka'
        meme.put(self.library, card)
        self.assertEqual(meme.search(self.library, 'quantumquokka')['results'][0]['id'], card['id'])
        card['status'] = 'draft'
        meme.put(self.library, card)
        self.assertEqual(meme.search(self.library, 'quantumquokka')['results'], [])
        self.assertEqual(meme.search(self.library, 'quantumquokka', drafts=True)['results'][0]['id'], card['id'])
        (self.library / 'cards' / (card['id'] + '.json')).unlink()
        meme.build(self.library)
        self.assertEqual(meme.search(self.library, 'quantumquokka', drafts=True)['results'], [])

    def test_sync_preserves_editorial_and_layout(self):
        before = meme.get_card(self.library, 'imgflip-181913649')
        before['stats']['public_listing_rank'] = 42
        meme.put(self.library, before)
        response = {'success': True, 'data': {'memes': [{'id': '181913649', 'name': 'Provider name changed',
            'url': 'https://i.imgflip.com/30b1gx.jpg', 'width': 1200, 'height': 1200, 'box_count': 2, 'captions': 99}]}}
        with patch.object(meme, 'request', return_value=(json.dumps(response).encode(), 'application/json')):
            meme.sync_imgflip(self.library, 'image')
        after = meme.get_card(self.library, before['id'])
        self.assertEqual(before['annotation'], after['annotation'])
        self.assertEqual(before['layout'], after['layout'])
        self.assertEqual(before['aliases'], after['aliases'])
        self.assertEqual(after['stats']['captions_lifetime_estimate'], 99)
        self.assertEqual(after['stats']['public_listing_rank'], before['stats']['public_listing_rank'])

    def test_invalid_put_does_not_replace_good_card(self):
        before = meme.get_card(self.library, 'imgflip-181913649')
        bad = copy.deepcopy(before)
        bad['layout']['boxes'][0]['x'] = 1.5
        with self.assertRaises(ValueError): meme.put(self.library, bad)
        self.assertEqual(meme.get_card(self.library, before['id']), before)
        bad = copy.deepcopy(before); bad['asset']['path'] = '../../escape.jpg'
        with self.assertRaises(ValueError): meme.put(self.library, bad)

    def test_render_contract_and_actual_english_image(self):
        card = meme.get_card(self.library, 'imgflip-181913649')
        source = self.source / card['asset']['path']
        target = self.library / card['asset']['path']
        target.parent.mkdir(parents=True, exist_ok=True); shutil.copy(source, target)
        output = Path(self.temp.name) / 'caption.png'
        result = meme.render(self.library, card['id'], ['Fix the bug', 'Rewrite the framework'], output)
        from PIL import Image
        with Image.open(output) as image:
            self.assertEqual(image.size, (1200, 1200))
        self.assertEqual(len(result['boxes']), 2)
        with self.assertRaises(ValueError): meme.render(self.library, card['id'], ['One caption missing'], output)
        with self.assertRaises(ValueError): meme.render(self.library, card['id'], ['A', 'B'], target)
        with self.assertRaises(ValueError): meme.render(self.library, 'imgflip-55311130', ['Test'], output)
        with self.assertRaises(ValueError): meme.render(self.library, card['id'], ['long ' * 10000, 'B'], output)

    def test_stale_concepts_and_vectors_fail_explicitly(self):
        with open(self.library / 'vectors.npz', 'wb') as f:
            np.savez_compressed(f, metadata=json.dumps({'format': meme.VECTOR_FORMAT, 'corpus': 'stale'}),
                                entries='[]', vectors=np.empty((0, 384), dtype=np.float32))
        with self.assertRaisesRegex(ValueError, 'stale'):
            meme.search(self.library, 'dilemma', semantic=True)
        lexicon = meme.concepts(self.library)
        lexicon.append({'id': 'new', 'terms': ['new concept']})
        meme.atomic_json(self.library / 'concepts.json', lexicon)
        with self.assertRaisesRegex(ValueError, 'mismatch'):
            meme.search(self.library, 'dilemma')

    def test_media_filter(self):
        for result in meme.search(self.library, 'dilemma', media_type='image')['results']:
            self.assertEqual(result['media_type'], 'image')

    def test_incremental_vectors_and_content_only_invalidation(self):
        class FakeModel:
            def __init__(self): self.calls = []
            def encode(self, texts, **kwargs):
                self.calls.append(texts)
                rng = np.random.default_rng(42)
                vectors = rng.normal(size=(len(texts), 384)).astype(np.float32)
                return vectors / np.linalg.norm(vectors, axis=1, keepdims=True)
        model = FakeModel()
        def run_embed():
            return meme.embed(self.library, meme.DEFAULT_MODEL, revision='fake-test')
        with patch.object(meme, 'load_model', return_value=model):
            first = run_embed()
            second = run_embed()
            self.assertGreater(first['newly_encoded'], 0)
            self.assertEqual(second['newly_encoded'], 0)
            self.assertEqual(len(model.calls), 1)
            card = meme.get_card(self.library, 'imgflip-181913649')
            card['stats']['captions_lifetime_estimate'] += 1
            meme.put(self.library, card)
            unchanged = run_embed()
            self.assertEqual(unchanged['newly_encoded'], 0)
            card['annotation']['scenarios'][0] += ' with a different detail'
            meme.put(self.library, card)
            with self.assertRaisesRegex(ValueError, 'stale'):
                meme.search(self.library, 'test', mode='semantic')
            updated = run_embed()
            self.assertEqual(updated['newly_encoded'], 1)
            self.assertEqual(len(model.calls[-1]), 1)
            self.assertFalse(model.calls[-1][0].startswith(('passage: ', 'query: ')))
            meme.build(self.library)
            rebuilt = run_embed()
            self.assertEqual(rebuilt['newly_encoded'], 0)

    def test_query_cleanup_preserves_intent(self):
        self.assertEqual(meme.normalize_query('I want the meme about choosing B'), 'choosing B')
        self.assertEqual(meme.normalize_query('Choosing road B between roads A and B'), 'Choosing road B between roads A and B')
        self.assertEqual(meme.normalize_query('Find a meme about two roads with B selected'), 'two roads with B selected')


if __name__ == '__main__':
    unittest.main(verbosity=2)

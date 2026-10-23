"""Integration checks with the installed local model, no network permitted."""
from pathlib import Path
import socket
import unittest
from unittest.mock import patch

import numpy as np
import meme


@unittest.skipUnless((meme.ROOT / 'catalog' / 'vectors.npz').exists(), 'Run scripts/meme embed first')
class LocalModelTests(unittest.TestCase):
    def test_cold_offline_search_and_real_model_vectors(self):
        library = meme.ROOT / 'catalog'
        metadata, entries, matrix = meme.read_vectors(library)
        self.assertEqual(matrix.shape[1], metadata['dimension'])
        self.assertEqual(metadata['model'], meme.DEFAULT_MODEL)
        self.assertTrue(np.allclose(np.linalg.norm(matrix, axis=1), 1, atol=1e-5))
        db = meme.connect(library)
        ready = db.execute("SELECT count(*) FROM cards WHERE status='ready'").fetchone()[0]
        db.close()
        self.assertEqual(len({e['card_id'] for e in entries}), ready)
        meme.load_model.cache_clear()
        with patch.object(socket.socket, 'connect', side_effect=AssertionError('search attempted network')), \
             patch.object(socket, 'create_connection', side_effect=AssertionError('search attempted network')):
            result = meme.search(library, 'Choosing road B at a fork between roads A and B')
            self.assertEqual(result['mode'], 'semantic')
            self.assertEqual(result['candidate_count'], 5)
            self.assertEqual(len({r['id'] for r in result['results']}), 5)
            self.assertEqual(result['stage'], 'candidate_retrieval')
            self.assertTrue(result['selection_required'])
            self.assertEqual(result['expanded_concepts'], [])
            self.assertIn('imgflip-124822590', [r['id'] for r in result['results']])
            self.assertIsNotNone(result['results'][0]['ranking']['semantic_similarity'])
            videos = meme.search(library, 'Quietly retreat after saying something embarrassing', media_type='video', mode='semantic')
            self.assertTrue(videos['results'])
            self.assertTrue(all(r['media_type'] == 'video' for r in videos['results']))
            unrelated = meme.search(library, 'What is the weather in Taipei tomorrow?')
            self.assertTrue(unrelated['selection_required'])
            self.assertEqual(len(unrelated['results']), 5)
            # Rebuilding unchanged cards must not require recomputing embeddings.
            meme.build(library)
            reuse = meme.embed(library, offline=True)
            self.assertEqual(reuse['newly_encoded'], 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)

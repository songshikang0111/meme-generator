"""Offline checks for bounded public-listing collection and metadata preservation."""
import copy
import hashlib
from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
import urllib.robotparser

import collect_imgflip as collect
import meme


def html(kind='image', explicit='61579'):
    path = '/gif-maker/' if kind == 'gif' else '/memegenerator/'
    return f'''<button class="i-select-btn">Top <small>30 days</small></button>
    <div class="mt-boxes"><div class="mt-box"><h3 class="mt-title">
    <a href="/memetemplate/{explicit}/One-Does-Not-Simply">One &amp; Two</a></h3>
    <div><a><img src="//i.imgflip.com/4/1bij.jpg"></a></div>
    <a href="{path}{explicit}/One-Does-Not-Simply">Add Caption</a></div></div>
    <a class="pager-next l but" href="{collect.LISTINGS[kind]}?page=2">Next</a>'''


class CollectorTests(unittest.TestCase):
    def test_visible_cards_entities_ids_and_pagination(self):
        items, next_url = collect.parse_listing(html(), 'image')
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['template_id'], '61579')
        self.assertEqual(items[0]['name'], 'One & Two')
        self.assertEqual(next_url, 'https://imgflip.com/memetemplates?page=2')
        self.assertEqual(items[0]['original_url_candidate'], 'https://i.imgflip.com/1bij.jpg')
        videos, _ = collect.parse_listing(html('gif'), 'gif')
        self.assertTrue(videos[0]['preview_url'].endswith('.jpg'))
        self.assertTrue(videos[0]['original_url_candidate'].endswith('.mp4'))
        proxied, _ = collect.parse_listing(html().replace('//i.imgflip.com/4/', '/i-view/4/'), 'image')
        self.assertEqual(proxied[0]['template_id'], '61579')

    def test_changed_markup_or_id_conflict_stops(self):
        with self.assertRaisesRegex(ValueError, 'disagree'):
            collect.parse_listing(html(explicit='123'), 'image')
        with self.assertRaisesRegex(ValueError, 'No templates'):
            collect.parse_listing('<h1>Please verify your browser</h1>', 'gif')
        with self.assertRaisesRegex(ValueError, 'Top 30 days'):
            collect.parse_listing(html().replace('30 days', 'All time'), 'image')

    def test_robots_scope_cache_and_no_retry_on_429(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = collect.GentleClient(Path(tmp))
            client.robots = urllib.robotparser.RobotFileParser()
            client.robots.parse(['User-agent: *', 'Disallow: /memetemplates'])
            with self.assertRaisesRegex(ValueError, 'robots'):
                client.fetch('https://imgflip.com/memetemplates')
            self.assertEqual(client.network_requests, 0)
            with self.assertRaisesRegex(ValueError, 'Only public'):
                client.fetch('https://imgflip.com/orig/example.jpg')
            url = 'https://imgflip.com/gif-templates'
            error = urllib.error.HTTPError(url, 429, 'Too Many Requests', {}, BytesIO())
            with patch.object(client.opener, 'open', side_effect=error) as opened:
                with self.assertRaises(urllib.error.HTTPError): client.fetch(url)
                self.assertEqual(opened.call_count, 1)
            self.assertEqual(list(Path(tmp).glob('*.json')), [])
            cache = Path(tmp) / (hashlib.sha256(url.encode()).hexdigest() + '.json')
            meme.atomic_json(cache, {'url': url, 'retrieved_at': collect.now(), 'text': html('gif'), 'sha256': 'test', 'bytes': 100})
            with patch.object(client.opener, 'open', side_effect=AssertionError('cached request used network')):
                self.assertTrue(client.fetch(url)['from_cache'])

    def test_import_preserves_editorial_and_marks_unverified_media(self):
        with tempfile.TemporaryDirectory() as tmp:
            library = Path(tmp)
            old = meme.read_json(meme.ROOT / 'catalog/cards/imgflip-181913649.json')
            meme.atomic_json(library / 'cards' / (old['id'] + '.json'), old)
            original = copy.deepcopy(old)
            groups = []
            for kind, identifier in [('image', '181913649'), ('gif', '61579')]:
                groups.append({'type': kind, 'ranking_basis': 'test', 'templates': [{
                    'template_id': identifier, 'name': 'Provider name', 'page_url': 'https://imgflip.com/memetemplate/' + identifier,
                    'preview_url': 'https://i.imgflip.com/4/1bij.jpg', 'original_url_candidate': 'https://i.imgflip.com/1bij.mp4',
                    'listing_url': collect.BASE + collect.LISTINGS[kind], 'listing_rank': 1, 'listing_page': 1,
                    'retrieved_at': collect.now(), 'id_basis': 'test'}]})
            result = collect.import_records(library, groups)
            after = meme.get_card(library, old['id'])
            for key in ('annotation', 'layout', 'aliases', 'status', 'name'):
                self.assertEqual(after[key], original[key])
            self.assertEqual(after['asset']['url'], original['asset']['url'])
            new = meme.get_card(library, 'imgflip-61579')
            self.assertEqual(new['status'], 'draft')
            self.assertEqual(new['media_type'], 'video')
            self.assertNotIn('url', new['asset'])
            self.assertEqual(new['asset']['url_status'], 'candidate_requires_detail_page_verification')
            self.assertEqual(result['existing_ready_preserved'], 1)
            self.assertEqual(result['added'], 1)

    def test_mixed_listings_classify_animation_before_collection(self):
        mixed = html().replace('/memegenerator/61579/', '/gif-maker/61579/')
        items, _ = collect.parse_listing(mixed, 'image')
        self.assertEqual(items[0]['type'], 'gif')
        self.assertTrue(items[0]['original_url_candidate'].endswith('.mp4'))

    def test_detail_resolution_uses_original_not_poster(self):
        video = '<video id="mtm-video" width="358" height="346" poster="//i.imgflip.com/2/6t2829.jpg"><source src="//i.imgflip.com/6t2829.mp4" type="video/mp4"></video>'
        url, dimensions = meme.parse_imgflip_detail(video, 'video')
        self.assertEqual(url, 'https://i.imgflip.com/6t2829.mp4')
        self.assertEqual(dimensions, {'width': 358, 'height': 346})
        image = '<img id="mtm-img" src="//i.imgflip.com/b6xvw.jpg" width="480" height="360">'
        self.assertEqual(meme.parse_imgflip_detail(image, 'image')[0], 'https://i.imgflip.com/b6xvw.jpg')
        with self.assertRaises(ValueError): meme.parse_imgflip_detail(video, 'image')
        with self.assertRaises(ValueError): meme.parse_imgflip_detail(image.replace('i.imgflip.com', 'example.org'), 'image')
        with self.assertRaises(ValueError): meme.parse_imgflip_detail('<meta property="og:image" content="poster.jpg">', 'video')

    def test_import_conflict_is_checked_before_any_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            library = Path(tmp)
            old = meme.read_json(meme.ROOT / 'catalog/cards/imgflip-171219241.json')
            target = library / 'cards' / (old['id'] + '.json')
            meme.atomic_json(target, old)
            before = target.read_bytes()
            group = {'type': 'image', 'templates': [{'template_id': '171219241'}]}
            with self.assertRaisesRegex(ValueError, 'Media type conflict'):
                collect.import_records(library, [group])
            self.assertEqual(target.read_bytes(), before)
            self.assertFalse((library / 'index.sqlite3').exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)

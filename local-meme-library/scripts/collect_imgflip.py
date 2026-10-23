#!/usr/bin/env python3
"""Collect a bounded template shortlist from Imgflip's public HTML pagination."""
import argparse
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
import urllib.parse

import meme

from imgflip_http import BASE, LISTINGS, GentleClient, now
RIGHTS = 'Third-party user-uploaded media; rights remain with the respective rights holders. No separate redistribution license has been obtained.'



class ListingParser(HTMLParser):
    """Read visible template cards and the next-page link, without executing JS."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.items = []
        self.next_url = None
        self.current = None
        self.depth = 0
        self.in_title = False
        self.in_sort_label = False
        self.sort_label = ''

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = attrs.get('class', '').split()
        if tag == 'button' and 'i-select-btn' in classes:
            self.in_sort_label = True
        if tag == 'a' and 'pager-next' in classes:
            self.next_url = urllib.parse.urljoin(BASE, attrs.get('href', ''))
        if tag == 'div':
            if self.current is not None:
                self.depth += 1
            elif 'mt-box' in classes:
                self.current = {'name': '', 'links': []}
                self.depth = 1
        if self.current is None:
            return
        if 'mt-animated-label' in classes:
            self.current['animated'] = True
        if tag == 'h3' and 'mt-title' in classes:
            self.in_title = True
        if tag == 'a' and attrs.get('href'):
            self.current['links'].append(attrs['href'])
            if self.in_title:
                self.current['page_url'] = urllib.parse.urljoin(BASE, attrs['href'])
        if tag == 'img':
            self.current['preview_url'] = urllib.parse.urljoin(BASE, attrs.get('src', ''))

    def handle_data(self, data):
        if self.in_sort_label:
            self.sort_label += data
        if self.current is not None and self.in_title:
            self.current['name'] += data

    def handle_endtag(self, tag):
        if tag == 'button':
            self.in_sort_label = False
        if tag == 'h3':
            self.in_title = False
        if tag == 'div' and self.current is not None:
            self.depth -= 1
            if self.depth == 0:
                self.items.append(self.current)
                self.current = None


def parse_listing(html, kind):
    parser = ListingParser()
    parser.feed(html)
    items = []
    for raw in parser.items:
        name = raw['name'].strip()
        preview = urllib.parse.urlsplit(raw.get('preview_url', ''))
        pattern = (r'/(?:[0-9]+/)?([a-z0-9]+)\.(jpg|jpeg|png|webp|gif)' if preview.netloc == 'i.imgflip.com'
                   else r'/i-view/(?:[0-9]+/)?([a-z0-9]+)\.(jpg|jpeg|png|webp|gif)' if preview.netloc == 'imgflip.com' else None)
        match = re.fullmatch(pattern, preview.path) if pattern else None
        if not match or not name:
            raise ValueError('Unexpected template markup; stop rather than guess missing metadata')
        code, ext = match.groups()
        encoded_id = str(int(code, 36))
        explicit = {m.group(1) for link in raw['links']
                    if (m := re.match(r'/(?:meme|memetemplate|memegenerator|gif-maker)/(\d+)(?:/|$)', link))}
        if len(explicit) > 1 or (explicit and encoded_id not in explicit):
            raise ValueError('Template ID and thumbnail filename disagree')
        identifier = next(iter(explicit), encoded_id)
        # This naming convention is observed in the public API's source URLs.
        # It is recorded as an unverified candidate, not a verified media download.
        actual_type = 'gif' if raw.get('animated') or any(link.startswith('/gif-maker/') for link in raw['links']) else 'image'
        if kind == 'gif' and actual_type != 'gif':
            raise ValueError('GIF listing contains an unexpected non-animated template')
        original = 'https://i.imgflip.com/' + code + ('.mp4' if actual_type == 'gif' else '.' + ext)
        items.append({'template_id': identifier, 'name': name, 'page_url': raw['page_url'],
                      'preview_url': raw['preview_url'], 'original_url_candidate': original,
                      'type': actual_type,
                      'id_basis': 'explicit_page_link_and_thumbnail' if explicit else 'base36_thumbnail_filename'})
    if not items:
        raise ValueError('No templates found; possible markup change or access challenge')
    if kind == 'image' and ' '.join(parser.sort_label.split()) != 'Top 30 days':
        raise ValueError('The static listing no longer identifies its ranking as Top 30 days')
    return items, parser.next_url



def collect_kind(client, kind, target):
    url = BASE + LISTINGS[kind]
    seen_urls, seen_ids, items, pages = set(), set(), [], []
    raw_position = 0
    excluded_other_media = 0
    duplicate_ids = 0
    # A hard bound prevents uncontrolled crawling after markup or pagination changes.
    for page_number in range(1, 21):
        if url in seen_urls:
            raise ValueError('Pagination loop detected')
        seen_urls.add(url)
        response = client.fetch(url)
        records, next_url = parse_listing(response['text'], kind)
        pages.append({k: v for k, v in response.items() if k != 'text'})
        added = 0
        for record in records:
            raw_position += 1
            if record['type'] != kind:
                excluded_other_media += 1
                continue
            identifier = record['template_id']
            if identifier in seen_ids:
                duplicate_ids += 1
                continue
            seen_ids.add(identifier)
            items.append({**record, 'listing_rank': raw_position, 'listing_page': page_number,
                          'type_rank': len(items) + 1,
                          'listing_url': url, 'retrieved_at': response['retrieved_at']})
            added += 1
            if len(items) == target:
                break
        print(json.dumps({'type': kind, 'page': page_number, 'unique_templates': len(items),
                          'cached': response['from_cache']}), file=sys.stderr, flush=True)
        if len(items) == target or not next_url:
            break
        if not added:
            raise ValueError('Pagination added no unique records; stopping')
        parts = urllib.parse.urlsplit(next_url)
        if parts.path != LISTINGS[kind] or urllib.parse.parse_qs(parts.query) != {'page': [str(page_number + 1)]}:
            raise ValueError('Unexpected next-page link; stopping')
        url = next_url
    return {'type': kind, 'ranking_basis': 'public_mixed_top_30_days_filtered_to_images' if kind == 'image' else 'public_popular_listing_unspecified_time_window',
            'excluded_other_media': excluded_other_media, 'duplicate_ids': duplicate_ids,
            'requested': target, 'collected': len(items), 'pages': pages, 'templates': items}


def import_records(library, groups):
    added, updated, ready_before = 0, 0, 0
    # Validate conflicts for the entire collection before writing any cards.
    ids = set()
    for group in groups:
        for item in group['templates']:
            identifier = 'imgflip-' + item['template_id']
            if identifier in ids:
                raise ValueError('Duplicate template across media groups: ' + identifier)
            ids.add(identifier)
            path = library / 'cards' / (identifier + '.json')
            if path.exists():
                card = meme.valid(meme.read_json(path))
                if card['media_type'] != ('video' if group['type'] == 'gif' else 'image'):
                    raise ValueError('Media type conflict for ' + identifier)
    for group in groups:
        kind = group['type']
        for item in group['templates']:
            identifier = 'imgflip-' + item['template_id']
            path = library / 'cards' / (identifier + '.json')
            if path.exists():
                card = meme.valid(meme.read_json(path))
                if card['media_type'] != ('video' if kind == 'gif' else 'image'):
                    raise ValueError('Media type conflict for ' + identifier)
                updated += 1
                ready_before += card['status'] == 'ready'
            else:
                added += 1
                card = {'schema_version': 1, 'id': identifier, 'name': item['name'], 'language': 'en',
                        'aliases': [], 'status': 'draft', 'media_type': 'video' if kind == 'gif' else 'image',
                        'source': {'provider': 'imgflip', 'template_id': item['template_id'], 'rights': RIGHTS,
                                   'page_url': item['page_url'], 'retrieved_at': item['retrieved_at']},
                        'asset': {}, 'stats': {}, 'layout': {'status': 'unreviewed', 'boxes': []}}
            card['source']['public_listing'] = {k: item[k] for k in ('listing_url', 'listing_rank', 'listing_page', 'retrieved_at', 'id_basis')}
            card['source']['public_listing']['type_rank'] = item.get('type_rank', item['listing_rank'])
            card['source']['public_listing']['ranking_basis'] = group['ranking_basis']
            card['asset']['preview_url'] = item['preview_url']
            if not card['asset'].get('url'):
                # Save the observed source pattern separately until confirmed by a
                # template detail page. A thumbnail is never treated as a full video.
                card['asset']['original_url_candidate'] = item['original_url_candidate']
                card['asset']['url_status'] = 'candidate_requires_detail_page_verification'
            card['stats']['public_listing_rank'] = item['listing_rank']
            meme.atomic_json(path, meme.valid(card))
    return {'added': added, 'updated': updated, 'existing_ready_preserved': ready_before, **meme.build(library)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--library', type=Path, default=meme.ROOT / 'catalog')
    parser.add_argument('--per-type', type=int, default=500)
    parser.add_argument('--delay', type=float, default=3)
    parser.add_argument('--cache', type=Path, default=meme.ROOT / '.runtime' / 'imgflip-listings')
    args = parser.parse_args()
    if not 1 <= args.per_type <= 500:
        parser.error('--per-type must be between 1 and 500')
    library = args.library.resolve()
    report_path = library / 'collections' / 'imgflip-public-listings.json'
    groups = []
    try:
        client = GentleClient(args.cache, args.delay)
        robots = client.load_robots()
        for kind in ('image', 'gif'):
            groups.append(collect_kind(client, kind, args.per_type))
        # Import only after both bounded listings have been collected successfully.
        imported = import_records(library, groups)
        report = {'collected_at': now(), 'robots': robots, 'request_delay_seconds': client.delay,
                  'network_requests': client.network_requests, 'cache_hits': client.cache_hits,
                  'note': 'Public HTML listing snapshot, not a licensed media bundle. GIF ranking time window is not stated on the listing. Source URLs beyond the free API are unverified candidates until detail-page resolution. New cards remain drafts.',
                  'groups': groups, 'import': imported}
        meme.atomic_json(report_path, report)
        print(json.dumps({'report': str(report_path), 'network_requests': client.network_requests,
                          'cache_hits': client.cache_hits, 'groups': [{k: g[k] for k in ('type', 'collected', 'ranking_basis')} for g in groups],
                          **imported}, indent=2))
    except (ValueError, OSError, KeyError) as exc:
        print(json.dumps({'error': str(exc), 'partial_groups_collected': [g['type'] for g in groups],
                          'note': 'Stopped without retries or bypasses; successful pages remain cached for resumption.'}), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())

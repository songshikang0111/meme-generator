#!/usr/bin/env python3
"""Local meme retrieval: offline text embeddings, optional FTS, caption rendering."""
import argparse
import hashlib
from functools import lru_cache
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = 'sentence-transformers/all-MiniLM-L6-v2'
DEFAULT_MODEL_REVISION = '1110a243fdf4706b3f48f1d95db1a4f5529b4d41'
MODEL_REVISIONS = {DEFAULT_MODEL: DEFAULT_MODEL_REVISION,
                   'intfloat/multilingual-e5-small': '614241f622f53c4eeff9890bdc4f31cfecc418b3'}
VECTOR_FORMAT = 2
SCHEMA = """
CREATE TABLE IF NOT EXISTS cards(id TEXT PRIMARY KEY, status TEXT, media_type TEXT,
 name TEXT, document TEXT, digest TEXT, concepts TEXT, payload TEXT);
CREATE VIRTUAL TABLE IF NOT EXISTS search USING fts5(
 id UNINDEXED, title, keywords, scenarios, mechanism, visual, concepts);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT);
CREATE TABLE IF NOT EXISTS semantic_docs(
 key TEXT PRIMARY KEY, card_id TEXT, kind TEXT, document TEXT, digest TEXT);
CREATE INDEX IF NOT EXISTS semantic_docs_card ON semantic_docs(card_id);
"""


def emit(value):
    print(json.dumps(value, ensure_ascii=False, indent=2))


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def atomic_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix='.' + path.name)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write('\n')
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def inside(library, relative):
    path = (library / relative).resolve()
    if Path(relative).is_absolute() or not path.is_relative_to(library.resolve()):
        raise ValueError('asset.path must be relative to the library directory')
    return path


def valid(card):
    if card.get('schema_version') != 1:
        raise ValueError('schema_version must be 1')
    if not re.fullmatch(r'[a-z][a-z0-9-]{1,100}', card.get('id', '')):
        raise ValueError('Invalid stable ID')
    if not isinstance(card.get('name'), str) or not card['name'].strip():
        raise ValueError('name must not be empty')
    if card.get('status') not in ('draft', 'ready'):
        raise ValueError('status must be draft or ready')
    if card.get('media_type') not in ('image', 'video'):
        raise ValueError('media_type must be image or video')
    for key in ('source', 'asset'):
        if not isinstance(card.get(key), dict):
            raise ValueError(key + ' must be an object')
    if not card['source'].get('provider') or not card['source'].get('rights'):
        raise ValueError('source requires provider and rights')
    for value in card.get('aliases', []):
        if not isinstance(value, str):
            raise ValueError('aliases must be an array of strings')
    if card['status'] == 'ready':
        a = card.get('annotation', {})
        for field in ('summary', 'visual', 'mechanism', 'basis'):
            if not isinstance(a.get(field), str) or not a[field].strip():
                raise ValueError('Ready cards require annotation.' + field)
        for field in ('scenarios', 'keywords', 'roles', 'emotions', 'avoid'):
            if not isinstance(a.get(field), list) or not a[field] or not all(isinstance(x, str) and x.strip() for x in a[field]):
                raise ValueError('Ready cards require a nonempty string array annotation.' + field)
        if not a.get('examples') or not all(isinstance(e.get('texts'), list) and e['texts'] and all(isinstance(t, str) for t in e['texts']) and isinstance(e.get('why'), str) for e in a['examples']):
            raise ValueError('Ready cards require examples: [{texts: [...], why: ...}]')
    layout = card.get('layout', {'status': 'unreviewed', 'boxes': []})
    if layout.get('status') not in ('unreviewed', 'reviewed'):
        raise ValueError('Invalid layout.status')
    boxes = layout.get('boxes', [])
    if layout['status'] == 'reviewed' and not boxes:
        raise ValueError('Reviewed layouts require text boxes')
    for box in boxes:
        for key in ('x', 'y', 'w', 'h'):
            if not isinstance(box.get(key), (int, float)) or not math.isfinite(box[key]):
                raise ValueError('Text boxes require finite numeric x,y,w,h')
        if not (0 <= box['x'] < 1 and 0 <= box['y'] < 1 and 0 < box['w'] <= 1 and 0 < box['h'] <= 1 and box['x'] + box['w'] <= 1.00001 and box['y'] + box['h'] <= 1.00001):
            raise ValueError('Text box exceeds relative coordinate bounds 0–1')
        if not box.get('role'):
            raise ValueError('Text boxes require a role')
    return card


def connect(library, create=False):
    path = library / 'index.sqlite3'
    if not path.exists() and not create:
        raise ValueError('Index missing; run build first')
    library.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    return db


def tokens(text):
    text = unicodedata.normalize('NFKC', text).lower()
    return list(dict.fromkeys(re.findall(r'[a-z0-9]+', text)))


def concepts(library):
    path = library / 'concepts.json'
    return read_json(path) if path.exists() else []


def match_concepts(text, lexicon):
    text = unicodedata.normalize('NFKC', text).lower()
    found = []
    for concept in lexicon:
        for term in [concept['id']] + concept['terms']:
            term = term.lower()
            pattern = r'(?<![a-z0-9])' + re.escape(term) + r'(?![a-z0-9])' if re.fullmatch('[a-z0-9 -]+', term) else re.escape(term)
            if re.search(pattern, text):
                found.append(concept)
                break
    return found


def sections(card, lexicon):
    a = card.get('annotation', {})
    title = ' '.join([card['name']] + card.get('aliases', []))
    keywords = ' '.join(a.get('keywords', []) + a.get('emotions', []))
    scenarios = ' '.join(a.get('scenarios', []))
    mechanism = a.get('summary', '') + ' ' + a.get('mechanism', '')
    visual = a.get('visual', '') + ' ' + ' '.join(a.get('roles', []))
    text = '\n'.join([title, keywords, scenarios, mechanism, visual])
    matched = match_concepts(text, lexicon)
    expanded = ' '.join(' '.join([c['id']] + c['terms']) for c in matched)
    return text, [title, keywords, scenarios, mechanism, visual, expanded], [c['id'] for c in matched]


def semantic_documents(card):
    """Separate visual and joke views to avoid burying details in a long card.

    No synonym expansion, negative examples, provider stats or asset paths.
    """
    if card['status'] != 'ready':
        return []
    a = card['annotation']
    title = ' / '.join([card['name']] + card.get('aliases', []))
    docs = [('mechanism', f"{title}\n{a['summary']}\nHumor: {a['mechanism']}"),
            ('visual', f"{title}\nVisual: {a['visual']}\nRoles: {'; '.join(a['roles'])}")]
    for i, scenario in enumerate(a['scenarios']):
        docs.append((f'scenario-{i}', f"{title}\nScenario: {scenario}\n{a['summary']}"))
    return [{'key': card['id'] + ':' + kind, 'card_id': card['id'], 'kind': kind,
             'text': text, 'digest': hashlib.sha256(text.encode()).hexdigest()} for kind, text in docs]


def upsert(db, card, lexicon):
    text, fields, matched = sections(card, lexicon)
    payload = json.dumps(card, ensure_ascii=False, sort_keys=True)
    digest = hashlib.sha256(payload.encode()).hexdigest()
    db.execute('INSERT OR REPLACE INTO cards VALUES(?,?,?,?,?,?,?,?)',
               (card['id'], card['status'], card['media_type'], card['name'], text, digest, json.dumps(matched), payload))
    db.execute('DELETE FROM search WHERE id=?', (card['id'],))
    db.execute('INSERT INTO search VALUES(?,?,?,?,?,?,?)', (card['id'], *(' '.join(tokens(f)) for f in fields)))
    db.execute('DELETE FROM semantic_docs WHERE card_id=?', (card['id'],))
    for doc in semantic_documents(card):
        db.execute('INSERT INTO semantic_docs VALUES(?,?,?,?,?)',
                   (doc['key'], doc['card_id'], doc['kind'], doc['text'], doc['digest']))


def mark_revision(db, lexicon):
    db.execute('INSERT OR REPLACE INTO meta VALUES(?,?)', ('revision', uuid.uuid4().hex))
    db.execute('INSERT OR REPLACE INTO meta VALUES(?,?)', ('concepts_hash', hashlib.sha256(json.dumps(lexicon, sort_keys=True, ensure_ascii=False).encode()).hexdigest()))
    signature = [(r[0], r[1]) for r in db.execute('SELECT key,digest FROM semantic_docs ORDER BY key')]
    db.execute('INSERT OR REPLACE INTO meta VALUES(?,?)', ('semantic_revision', hashlib.sha256(json.dumps(signature).encode()).hexdigest()))


def build(library):
    lexicon = concepts(library)
    cards = [valid(read_json(p)) for p in sorted((library / 'cards').glob('*.json'))]
    ids = [c['id'] for c in cards]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate card ID')
    for card in cards:
        if card['asset'].get('path'):
            inside(library, card['asset']['path'])
    db = connect(library, True)
    with db:
        db.execute('DELETE FROM cards')
        db.execute('DELETE FROM search')
        db.execute('DELETE FROM semantic_docs')
        for card in cards:
            upsert(db, card, lexicon)
        mark_revision(db, lexicon)
    db.close()
    return {'indexed': len(cards), 'ready': sum(c['status'] == 'ready' for c in cards)}


def put(library, card):
    valid(card)
    if card['asset'].get('path'):
        inside(library, card['asset']['path'])
    lexicon = concepts(library)
    db = connect(library, True)
    old_hash = db.execute("SELECT value FROM meta WHERE key='concepts_hash'").fetchone()
    new_hash = hashlib.sha256(json.dumps(lexicon, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    if old_hash and old_hash[0] != new_hash:
        db.close()
        raise ValueError('concepts.json changed; run build before put')
    atomic_json(library / 'cards' / (card['id'] + '.json'), card)
    with db:
        upsert(db, card, lexicon)
        mark_revision(db, lexicon)
    db.close()
    return {'updated': card['id'], 'status': card['status']}


def get_card(library, identifier):
    db = connect(library)
    row = db.execute('SELECT payload FROM cards WHERE id=?', (identifier,)).fetchone()
    db.close()
    if not row:
        raise ValueError('ID not found: ' + identifier)
    return json.loads(row[0])


@lru_cache(maxsize=2)
def load_model(name, offline=True, revision=None):
    # Use ordinary HTTPS downloads; Xet's Rust downloader may ignore SOCKS proxies.
    os.environ.setdefault('HF_HUB_DISABLE_XET', '1')
    try:
        from sentence_transformers import SentenceTransformer
        import torch
    except ImportError:
        raise ValueError('Local embedding environment required; use scripts/meme or run scripts/setup_embeddings.sh first')
    torch.set_num_threads(4)
    path = ROOT / '.runtime' / 'models' / name.replace('/', '--') / (revision or 'main')
    if not offline:
        from huggingface_hub import snapshot_download
        snapshot_download(name, revision=revision, local_dir=path, allow_patterns=[
            'config.json', 'modules.json', 'sentence_bert_config.json', 'config_sentence_transformers.json', '1_Pooling/config.json',
            'tokenizer.json', 'tokenizer_config.json', 'special_tokens_map.json',
            'vocab.txt', 'sentencepiece.bpe.model', 'model.safetensors', 'README.md'], max_workers=3)
    if not (path / 'model.safetensors').is_file():
        raise ValueError('Local model download incomplete; run embed')
    # The query path is a physical local directory, never a Hub URL.
    return SentenceTransformer(str(path), device='cpu', local_files_only=True,
                               trust_remote_code=False, model_kwargs={'use_safetensors': True})


def read_vectors(library):
    path = library / 'vectors.npz'
    if not path.exists():
        raise ValueError('Vector index missing; run embed first')
    stat = path.stat()
    return _read_vectors(str(path), stat.st_mtime_ns, stat.st_size)


@lru_cache(maxsize=4)
def _read_vectors(path, modified_ns, size):
    import numpy as np
    try:
        with np.load(path, allow_pickle=False) as data:
            metadata = json.loads(str(data['metadata'].item()))
            vectors = data['vectors'].copy()
            entries = json.loads(str(data['entries'].item()))
    except (KeyError, OSError, ValueError) as exc:
        raise ValueError('Cannot read vector index; rerun embed: ' + str(exc))
    if metadata.get('format') != VECTOR_FORMAT:
        raise ValueError('Vector format changed; rerun embed')
    if vectors.ndim != 2 or vectors.shape[0] != len(entries) or not np.isfinite(vectors).all():
        raise ValueError('Vector index is corrupt; rerun embed')
    return metadata, entries, vectors


def embed(library, model_name=DEFAULT_MODEL, revision=None, offline=False):
    import numpy as np
    if revision is None:
        revision = MODEL_REVISIONS.get(model_name)
    db = connect(library)
    rows = db.execute('SELECT * FROM semantic_docs ORDER BY key').fetchall()
    corpus = db.execute("SELECT value FROM meta WHERE key='semantic_revision'").fetchone()
    db.close()
    if not rows:
        raise ValueError('No semantic documents to encode; build an index containing ready cards first')
    cache = {}
    if (library / 'vectors.npz').exists():
        old, entries, old_vectors = read_vectors(library)
        if old['model'] == model_name and old.get('model_revision') == revision:
            cache = {(e['key'], e['digest']): vector for e, vector in zip(entries, old_vectors)}
    needed = [r for r in rows if (r['key'], r['digest']) not in cache]
    local_weights = ROOT / '.runtime' / 'models' / model_name.replace('/', '--') / (revision or 'main') / 'model.safetensors'
    model = None
    if needed or not local_weights.is_file():
        model = load_model(model_name, offline=offline, revision=revision)
    if needed:
        prefix = 'passage: ' if 'e5' in model_name.lower() else ''
        encoded = model.encode([prefix + r['document'] for r in needed], normalize_embeddings=True,
                               show_progress_bar=False, batch_size=16)
        for row, vector in zip(needed, encoded):
            cache[(row['key'], row['digest'])] = vector
    matrix = np.array([cache[(r['key'], r['digest'])] for r in rows], dtype=np.float32)
    entries = [{'key': r['key'], 'card_id': r['card_id'], 'kind': r['kind'], 'digest': r['digest']} for r in rows]
    query_prefix = 'query: ' if 'e5' in model_name.lower() else ''
    metadata = {'format': VECTOR_FORMAT, 'model': model_name, 'model_revision': revision,
                'corpus': corpus[0], 'dimension': matrix.shape[1],
                'query_prefix': query_prefix}
    fd, tmp = tempfile.mkstemp(dir=library, suffix='.npz')
    try:
        with os.fdopen(fd, 'wb') as f:
            np.savez_compressed(f, metadata=json.dumps(metadata), entries=json.dumps(entries), vectors=matrix)
        os.replace(tmp, library / 'vectors.npz')
    finally:
        if os.path.exists(tmp): os.unlink(tmp)
    return {'cards': len({r['card_id'] for r in rows}), 'documents': len(rows),
            'newly_encoded': len(needed), 'reused': len(rows) - len(needed), **metadata}


def semantic_rank(library, db, query, media_type=None, limit=5):
    metadata, entries, matrix = read_vectors(library)
    corpus = db.execute("SELECT value FROM meta WHERE key='semantic_revision'").fetchone()
    if not corpus or metadata['corpus'] != corpus[0]:
        raise ValueError('Vector index is stale; run embed to encode new or changed documents')
    model = load_model(metadata['model'], offline=True, revision=metadata.get('model_revision'))
    vector = model.encode(metadata['query_prefix'] + query, normalize_embeddings=True, show_progress_bar=False)
    scores = matrix @ vector
    # Every card has several views; the best matching view determines recall.
    best = {}
    for entry, score in zip(entries, scores):
        identifier = entry['card_id']
        if identifier not in best or float(score) > best[identifier]['similarity']:
            best[identifier] = {'similarity': float(score), 'view': entry['kind']}
    # Filter with IDs only; fetch full cards only for the small candidate set.
    where = "status='ready'" + (' AND media_type=?' if media_type else '')
    eligible = {r['id'] for r in db.execute('SELECT id FROM cards WHERE ' + where, (media_type,) if media_type else ())}
    ordered = sorted((i for i in best if i in eligible), key=lambda i: (-best[i]['similarity'], i))[:limit]
    if not ordered:
        return [], metadata
    placeholders = ','.join('?' for _ in ordered)
    rows = {r['id']: r for r in db.execute('SELECT * FROM cards WHERE id IN (' + placeholders + ')', ordered)}
    return [(best[i], rows[i]) for i in ordered], metadata


def normalize_query(query):
    """Remove request boilerplate only; never invent a direction or joke."""
    text = unicodedata.normalize('NFKC', query).strip()
    text = re.sub(r'^(?:i (?:want|need)(?: to find)? (?:a|the) (?:meme|template|image) (?:about|for)|find (?:a|the) meme (?:about|for))\s+', '', text, flags=re.I)
    text = re.sub(r'\s+(?:meme|template)[.!?\s]*$', '', text, flags=re.I).strip()
    return text or query.strip()


def search(library, query, limit=5, media_type=None, drafts=False, semantic=False, mode=None):
    if not query.strip():
        raise ValueError('query must not be empty')
    search_text = normalize_query(query)
    db = connect(library)
    if mode is None:
        settings = library / 'retrieval.json'
        mode = 'hybrid' if semantic else (read_json(settings).get('default_mode', 'lexical') if settings.exists() else 'lexical')
    if mode not in ('lexical', 'semantic', 'hybrid'):
        raise ValueError('mode must be lexical, semantic, or hybrid')
    if drafts and mode != 'lexical':
        raise ValueError('Drafts lack semantic annotations; use --mode lexical --include-drafts')
    lexicon = concepts(library) if mode != 'semantic' else []
    current_hash = hashlib.sha256(json.dumps(lexicon, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    indexed_hash = db.execute("SELECT value FROM meta WHERE key='concepts_hash'").fetchone()
    if mode != 'semantic' and (not indexed_hash or indexed_hash[0] != current_hash):
        raise ValueError('Concept lexicon and index mismatch; run build')
    matched = match_concepts(search_text, lexicon) if mode != 'semantic' else []
    expanded = search_text + ' ' + ' '.join(' '.join([c['id']] + c['terms']) for c in matched)
    terms = tokens(expanded)[:200]
    candidates = {}
    if terms and mode != 'semantic':
        expression = ' OR '.join('"' + t.replace('"', '""') + '"' for t in terms)
        where = '' if drafts else " AND c.status='ready'"
        params = [expression]
        if media_type:
            where += ' AND c.media_type=?'
            params.append(media_type)
        rows = db.execute('SELECT c.*, bm25(search,0,7,6,4,2,1,5) AS rank FROM search '
                          'JOIN cards c ON c.id=search.id WHERE search MATCH ?' + where +
                          ' ORDER BY rank,c.id LIMIT 80', params).fetchall()
        for rank, row in enumerate(rows):
            candidates[row['id']] = {'row': row, 'score': 1 / (60 + rank + 1), 'lexical_rank': rank + 1}
    metadata = None
    if mode != 'lexical':
        scored, metadata = semantic_rank(library, db, search_text, media_type, 80 if mode == 'hybrid' else limit)
        for rank, (details, row) in enumerate(scored[:80]):
            entry = candidates.setdefault(row['id'], {'row': row, 'score': 0})
            entry['score'] += (1 / (60 + rank + 1)) if mode == 'hybrid' else details['similarity']
            entry['semantic_similarity'] = round(details['similarity'], 4)
            entry['semantic_rank'] = rank + 1
            entry['matched_view'] = details['view']
    db.close()
    results = []
    for entry in sorted(candidates.values(), key=lambda e: (-e['score'], e['row']['id']))[:limit]:
        row = entry['row']
        card = json.loads(row['payload'])
        a = card.get('annotation', {})
        path = card['asset'].get('path')
        results.append({'id': card['id'], 'name': card['name'], 'summary': a.get('summary', 'Not annotated'),
                        'visual': a.get('visual'), 'roles': a.get('roles', []),
                        'scenarios': a.get('scenarios', [])[:3], 'media_type': card['media_type'],
                        'asset_path': str(inside(library, path)) if path else None,
                        'asset_available': bool(path and inside(library, path).is_file()),
                        'layout_status': card.get('layout', {}).get('status', 'unreviewed'),
                        'matched_concepts': sorted(set(json.loads(row['concepts'])) & {c['id'] for c in matched}),
                        'ranking': {k: v for k, v in entry.items() if k != 'row'}})
    return {'query': query, 'search_text': search_text, 'mode': mode, 'model': metadata['model'] if metadata else None,
            'stage': 'candidate_retrieval', 'selection_required': True, 'candidate_count': len(results),
            'notice': 'Review these candidates before choosing. Cosine similarity is not a match probability; unrelated requests also have nearest neighbors.' if metadata else None,
            'expanded_concepts': [c['id'] for c in matched], 'results': results}


def request(url, max_bytes=30 * 1024 * 1024):
    if urllib.parse.urlsplit(url).scheme not in ('https', 'http'):
        raise ValueError('Only public HTTP(S) URLs are supported')
    req = urllib.request.Request(url, headers={'User-Agent': 'local-meme-library/0.1 (public template collection)'})
    with urllib.request.urlopen(req, timeout=40) as r:
        body = r.read(max_bytes + 1)
        if len(body) > max_bytes:
            raise ValueError('Response exceeds size limit')
        return body, r.headers.get('Content-Type', '')


def sync_imgflip(library, kind):
    from datetime import datetime, timezone
    kinds = ['image', 'gif'] if kind == 'both' else [kind]
    total, added = 0, 0
    for media in kinds:
        body, _ = request('https://api.imgflip.com/get_memes?type=' + media)
        response = json.loads(body)
        if not response.get('success'):
            raise ValueError('Imgflip: ' + str(response.get('error_message')))
        for rank, item in enumerate(response['data']['memes'], 1):
            identifier = 'imgflip-' + str(item['id'])
            path = library / 'cards' / (identifier + '.json')
            if path.exists():
                card = valid(read_json(path))
            else:
                added += 1
                card = {'schema_version': 1, 'id': identifier, 'name': item['name'], 'aliases': [],
                        'language': 'en',
                        'status': 'draft', 'media_type': 'video' if media == 'gif' else 'image',
                        'asset': {}, 'source': {}, 'layout': {'status': 'unreviewed', 'boxes': []}}
            card['asset']['url'] = item['url']
            card['source'].update({'provider': 'imgflip', 'template_id': str(item['id']),
                                  'page_url': 'https://imgflip.com/memetemplate/' + str(item['id']),
                                  'retrieved_at': datetime.now(timezone.utc).isoformat(),
                                  'rights': card['source'].get('rights') or 'Third-party user-uploaded media; rights remain with the respective rights holders. No separate redistribution license has been obtained.'})
            card['stats'] = {'width': item['width'], 'height': item['height'], 'box_count': item['box_count'],
                             'captions_lifetime_estimate': item.get('captions'), 'rank_30d': rank, 'list_type': media}
            atomic_json(path, valid(card))
            total += 1
    return {'received': total, 'new': added, **build(library)}


def download(library, identifier):
    card = get_card(library, identifier)
    url = card['asset'].get('url')
    if not url:
        raise ValueError('Asset has no remote URL')
    ext = Path(urllib.parse.urlsplit(url).path).suffix.lower()
    if ext not in ('.jpg', '.jpeg', '.png', '.webp', '.gif', '.mp4'):
        raise ValueError('Unsupported asset extension')
    body, content_type = request(url)
    if not content_type.startswith(('image/', 'video/')):
        raise ValueError('Server did not return image/video content: ' + content_type)
    relative = 'assets/' + identifier + ext
    target = inside(library, relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=target.parent)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(body)
        os.replace(tmp, target)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    card['asset'].update({'path': relative, 'sha256': hashlib.sha256(body).hexdigest()})
    put(library, card)
    return {'id': identifier, 'path': str(target), 'bytes': len(body)}


def wrap_text(draw, text, font, width, stroke):
    lines = []
    for paragraph in text.split('\n'):
        line = ''
        # Keep ordinary English words intact, while allowing CJK wrapping.
        units = re.findall(r'[a-zA-Z0-9]+(?:[\x27’-][a-zA-Z0-9]+)*|[^a-zA-Z0-9]', paragraph)
        for unit in units:
            trial = line + unit
            if draw.textbbox((0, 0), trial, font=font, stroke_width=stroke)[2] > width and line:
                lines.append(line.rstrip())
                line = unit.lstrip()
            else:
                line = trial
        lines.append(line.rstrip())
    return lines


def render(library, identifier, texts, output=None, mode='overlay', plan=False, font_path=None):
    if any(len(text) > 2000 for text in texts):
        raise ValueError('A text box exceeds 2000 characters; shorten the caption')
    card = get_card(library, identifier)
    if card['media_type'] != 'image':
        raise ValueError('Renderer supports still images only; use a video editor for motion templates')
    if mode == 'overlay':
        layout = card.get('layout', {})
        if layout.get('status') != 'reviewed':
            raise ValueError('Layout is unreviewed; review it first or explicitly use --mode top-caption')
        boxes = layout['boxes']
        if len(texts) != len(boxes):
            raise ValueError(f'Layout requires {len(boxes)} captions; received {len(texts)}')
    else:
        boxes = [{'role': 'Context caption above image', 'x': 0.02, 'y': 0.02, 'w': 0.96, 'h': 0.96, 'color': '#111111', 'stroke': 0}]
        texts = ['\n'.join(texts)]
    if plan:
        return {'id': identifier, 'mode': mode, 'boxes': [{**b, 'text': t} for b, t in zip(boxes, texts)]}
    if not output:
        raise ValueError('Rendering requires --output; use --plan to inspect without rendering')
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        raise ValueError('Caption rendering requires Pillow')
    relative = card['asset'].get('path')
    if not relative or not inside(library, relative).is_file():
        raise ValueError('Local asset missing; run download ' + identifier)
    image = Image.open(inside(library, relative)).convert('RGB')
    if not font_path:
        import subprocess
        try:
            font_path = subprocess.check_output(['fc-match', 'DejaVu Sans:style=Bold', '-f', '%{file}'], text=True).strip()
        except (OSError, subprocess.CalledProcessError):
            raise ValueError('Specify a TTF/TTC font with --font')
    if not font_path or not Path(font_path).is_file():
        raise ValueError('Font file does not exist')
    original_size = image.size
    if mode == 'top-caption':
        band = max(140, int(image.width * 0.25))
        canvas = Image.new('RGB', (image.width, image.height + band), 'white')
        canvas.paste(image, (0, band))
        image = canvas
        pixel_boxes = [(int(image.width * .03), 8, int(image.width * .94), band - 16)]
    else:
        pixel_boxes = [(round(b['x'] * image.width), round(b['y'] * image.height),
                        round(b['w'] * image.width), round(b['h'] * image.height)) for b in boxes]
    fitted = []
    for box, text, (x, y, width, height) in zip(boxes, texts, pixel_boxes):
        if not text.strip():
            continue
        layer = Image.new('RGBA', (width, height))
        draw = ImageDraw.Draw(layer)
        stroke = int(box.get('stroke', 1))
        padding = min(6, max(1, height // 12))
        found = None
        for size in range(min(90, max(12, int(image.width * .055))), 11, -1):
            font = ImageFont.truetype(font_path, size)
            try:
                if b'Bold' in font.get_variation_names():
                    font.set_variation_by_name('Bold')
            except (AttributeError, OSError):
                pass
            lines = wrap_text(draw, text, font, width - padding * 2, stroke)
            line_height = math.ceil(size * 1.35) + 2 * stroke
            if '\n' not in text and len(lines) > 1 and len(lines[-1].strip()) == 1:
                continue
            if len(lines) * line_height <= height - padding * 2 and all(draw.textbbox((0, 0), t, font=font, stroke_width=stroke)[2] <= width - padding * 2 for t in lines):
                found = (size, font, lines, line_height)
                break
        if not found:
            raise ValueError('Caption does not fit; shorten the text or adjust the layout. Role: ' + box['role'])
        size, font, lines, line_height = found
        top = (height - len(lines) * line_height) / 2
        for i, line in enumerate(lines):
            bounds = draw.textbbox((0, 0), line, font=font, stroke_width=stroke)
            left = padding if box.get('align') == 'left' else (width - (bounds[2] - bounds[0])) / 2
            draw.text((left - bounds[0], top + i * line_height - bounds[1]), line, font=font,
                      fill=box.get('color', '#111111'), stroke_width=stroke,
                      stroke_fill=box.get('stroke_color', '#ffffff'))
        if box.get('rotation'):
            layer = layer.rotate(-float(box['rotation']), resample=Image.Resampling.BICUBIC, expand=False)
        image.paste(layer, (x, y), layer)
        fitted.append({'role': box['role'], 'font_size': size, 'lines': lines, 'pixels': [x, y, width, height]})
    output = Path(output).expanduser().resolve()
    source_path = inside(library, relative)
    if output == source_path:
        raise ValueError('Cannot overwrite the original asset')
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output)
    return {'output': str(output), 'source_size': original_size, 'output_size': image.size, 'boxes': fitted}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--library', type=Path, default=ROOT / 'catalog')
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('sync-imgflip'); p.add_argument('--type', choices=['image', 'gif', 'both'], default='image')
    sub.add_parser('build'); sub.add_parser('stats')
    p = sub.add_parser('put'); p.add_argument('file', type=Path)
    p = sub.add_parser('pending'); p.add_argument('--limit', type=int, default=10)
    for command in ('show', 'download'):
        p = sub.add_parser(command); p.add_argument('id')
    p = sub.add_parser('search'); p.add_argument('query'); p.add_argument('--limit', type=int, default=5)
    p.add_argument('--type', choices=['image', 'video']); p.add_argument('--include-drafts', action='store_true'); p.add_argument('--semantic', action='store_true', help='Legacy alias for --mode hybrid')
    p.add_argument('--mode', choices=['lexical', 'semantic', 'hybrid'])
    p = sub.add_parser('embed'); p.add_argument('--model', default=DEFAULT_MODEL); p.add_argument('--revision'); p.add_argument('--offline', action='store_true')
    p = sub.add_parser('render'); p.add_argument('id'); p.add_argument('--text', action='append', required=True)
    p.add_argument('--output'); p.add_argument('--font'); p.add_argument('--mode', choices=['overlay', 'top-caption'], default='overlay'); p.add_argument('--plan', action='store_true')
    args = parser.parse_args()
    library = args.library.expanduser().resolve()
    try:
        if args.command == 'build': result = build(library)
        elif args.command == 'put': result = put(library, read_json(args.file))
        elif args.command == 'sync-imgflip': result = sync_imgflip(library, args.type)
        elif args.command == 'download': result = download(library, args.id)
        elif args.command == 'show':
            result = get_card(library, args.id)
            if result['asset'].get('path'):
                result['asset_absolute_path'] = str(inside(library, result['asset']['path']))
        elif args.command == 'search': result = search(library, args.query, max(1, min(args.limit, 30)), args.type, args.include_drafts, args.semantic, args.mode)
        elif args.command == 'embed': result = embed(library, args.model, args.revision, args.offline)
        elif args.command == 'render': result = render(library, args.id, args.text, args.output, args.mode, args.plan, args.font)
        elif args.command == 'stats':
            db = connect(library)
            result = {'library': str(library), 'counts': [dict(r) for r in db.execute('SELECT status,media_type,count(*) AS count FROM cards GROUP BY status,media_type')],
                      'local_assets': sum(1 for p in (library / 'assets').glob('*') if p.is_file()), 'vectors_present': (library / 'vectors.npz').exists()}
            db.close()
        else:
            db = connect(library)
            result = [dict(r) for r in db.execute("SELECT id,name,media_type FROM cards WHERE status='draft' ORDER BY id LIMIT ?", (max(1, args.limit),))]
            db.close()
        emit(result)
    except (ValueError, OSError, KeyError, TypeError, ImportError, sqlite3.Error) as exc:
        emit({'error': str(exc)})
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())

#!/usr/bin/env python3
"""Measure five-candidate recall for frozen English requests."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import statistics
import time

import meme


def evaluate(library, cases, modes):
    samples = []
    for case in cases:
        detail = {**case, 'search_text': meme.normalize_query(case['query']), 'modes': {}}
        for mode in modes:
            start = time.perf_counter()
            result = meme.search(library, case['query'], limit=5, mode=mode)
            elapsed = (time.perf_counter() - start) * 1000
            ids = [r['id'] for r in result['results']]
            relevant = case['relevant']
            found = sorted(set(ids) & set(relevant))
            detail['modes'][mode] = {'candidates': ids, 'relevant_retrieved': found,
                'hit_at5': bool(found) if relevant else None,
                'recall_at5': len(found) / len(set(relevant)) if relevant else None,
                'selection_required': result['selection_required'],
                'elapsed_ms': round(elapsed, 2)}
        samples.append(detail)
    metrics = {}
    groups = ['all_relevant'] + sorted({c['group'] for c in cases if c['relevant']})
    for mode in modes:
        metrics[mode] = {}
        for group in groups:
            rows = [s['modes'][mode] for s in samples if s['relevant'] and (group == 'all_relevant' or s['group'] == group)]
            if rows:
                metrics[mode][group] = {'count': len(rows),
                    'hit_at5': round(sum(r['hit_at5'] for r in rows) / len(rows), 4),
                    'recall_at5': round(sum(r['recall_at5'] for r in rows) / len(rows), 4)}
        times = [s['modes'][mode]['elapsed_ms'] for s in samples]
        metrics[mode]['timing'] = {'first_request_ms': times[0] if times else None,
            'subsequent_median_ms': round(statistics.median(times[1:]), 2) if len(times) > 1 else None}
    db = meme.connect(library)
    signature = db.execute("SELECT value FROM meta WHERE key='semantic_revision'").fetchone()[0]
    db.close()
    return {'evaluated_at': datetime.now(timezone.utc).isoformat(), 'semantic_corpus_hash': signature,
        'note': 'Editorial English development cases over the curated prototype catalog, with no agent rewriting at evaluation time. Hit@5 measures whether any annotated relevant template is retrieved; Recall@5 averages the fraction retrieved per request. This is not an independent blind test or real-world accuracy estimate. Unrelated requests are recorded separately and require agent review. Timing separates the first request from subsequent calls in the same process.',
        'metrics': metrics, 'samples': samples}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--library', type=Path, default=meme.ROOT / 'catalog')
    p.add_argument('--queries', type=Path, default=meme.ROOT / 'evaluation' / 'queries.json')
    p.add_argument('--output', type=Path, default=meme.ROOT / 'evaluation' / 'results.json')
    p.add_argument('--modes', nargs='+', choices=['lexical', 'semantic', 'hybrid'], default=['semantic'])
    args = p.parse_args()
    report = evaluate(args.library.resolve(), meme.read_json(args.queries), args.modes)
    meme.atomic_json(args.output, report)
    print(json.dumps({'output': str(args.output), 'metrics': report['metrics']}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

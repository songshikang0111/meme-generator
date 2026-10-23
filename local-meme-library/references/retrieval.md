# English embedding retrieval

## Contract

The agent translates non-English user intent into English before searching. The script performs embedding retrieval, not translation or final selection. Its default response contains five unique ready-card candidates (fewer when a media filter leaves fewer eligible records), with short descriptions and local media paths. The agent inspects candidates and chooses or offers alternatives. Evaluate whether useful templates are included in the shortlist; their exact order is secondary.

## Local architecture

- Canonical JSON cards hold English visual descriptions, joke mechanisms, scenarios, and caption guidance.
- SQLite holds card snapshots and short semantic documents. Each ready card contributes a mechanism view, a literal visual/role view, and a view per scenario. Negative usage warnings and provider statistics are excluded.
- `sentence-transformers/all-MiniLM-L6-v2` produces normalized 384-dimensional vectors on CPU. Its pinned revision is recorded in the vector file. The model is English-oriented and truncates beyond 256 wordpieces, so keep each view concise. No query/passage prefix is required for this model.
- Search embeds one English query, calculates cosine similarities, takes each card's highest-scoring view, filters by status/media, and returns five unique cards. Pure semantic search fetches only these candidate payloads from SQLite. It does not apply the optional lexical synonym groups.
- SQLite remains useful for storage, filtering, stable IDs, and incremental updates. Embeddings replace keyword-only matching for this workflow; they do not replace the database.

The current NumPy index performs an exact vector scan in native code. It avoids catalog traversal and avoids passing every description to the agent, but its runtime and memory still grow linearly with the number of views. A float32 matrix uses `views × 384 × 4` bytes before metadata; 100,000 cards with five views need about 768 MB for vector data. If measured corpus size or latency warrants it, replace candidate generation with an approximate nearest-neighbor index such as HNSW, preserving the same five-candidate interface and SQLite metadata. No vector database service is needed for this prototype.

## Setup and updates

```bash
scripts/setup_embeddings.sh
scripts/meme search 'choosing road B at a fork between roads A and B' --mode semantic --limit 5
scripts/meme put /absolute/path/complete-card.json
scripts/meme embed --offline
```

Setup requires network access once for dependencies and model weights. Search loads the physical local model directory with offline loading enabled. Model weights live under `.runtime/models/`; the wrapper uses `.venv/`. See [embedding-usage.md](embedding-usage.md) for versions and provenance.

`embed` reuses vectors whose view ID, text digest, model ID, and revision match. Editing one scenario re-encodes one view. Provider statistics, asset downloads, and layout changes do not invalidate embeddings. Semantic text changes cause an explicit stale-index error until `embed` runs. Model changes re-encode all views. Rebuilding unchanged JSON retains the same semantic corpus signature.

Optional `--mode lexical` supports exact names and draft discovery; `--mode hybrid` combines lexical and semantic ranks. The skill's normal path is English semantic retrieval with five candidates.

## Candidate recall checks

```bash
.venv/bin/python scripts/test_meme.py
.venv/bin/python scripts/test_semantic_live.py
.venv/bin/python scripts/evaluate_retrieval.py --modes semantic
```

`evaluation/queries.json` is a small editorial development set with English requests and relevant IDs. The report records Hit@5 (at least one relevant candidate) and Recall@5 (fraction of annotated relevant IDs included). It does not optimize or score first place. Unrelated requests are recorded separately because nearest-neighbor search still returns candidates; final suitability is an agent judgment. This development set is not an independent estimate of real-world accuracy or performance on a much larger library.

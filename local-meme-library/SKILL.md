---
name: local-meme-library
description: Search a local meme template library by scene, emotion, or joke; inspect candidate images and role descriptions; write captions, render still images, or plan remixes. Also use to add templates and maintain annotations. Designed for English-language meme communities, with English embedding queries even when the user speaks another language.
---

# Local Meme Library

Resolve this skill's absolute directory, then run `<skill-directory>/scripts/meme ...`. The wrapper selects the bundled Python environment. Commands return JSON and need no running service. Add `--library <absolute-directory>` before the subcommand to use another catalog. After initial model setup, embedding searches run locally without a key or network connection.

## Retrieve candidates, then inspect

1. Express the user's intent as a short **English search query**, even when their request is in another language. Translate faithfully: preserve visual constraints, roles, action, and any stated emotion. Do not invent a moral judgment, a preferred alternative, or an extra plot. For example, a translated request for two roads with B selected becomes `choosing road B at a fork between roads A and B`; do not add that B is wrong or that A was the original plan.
2. Run `search '<English query>' --mode semantic --limit 5`. These are **five candidate templates**, not a final answer or an automatic choice. Results include a brief visual description, roles, local asset paths, and matching view. Do not scan every card or dump the catalog into context. If the shortlist lacks an appropriate candidate, try one more faithful query emphasizing a different stated feature, such as the physical scene rather than the emotion.
3. Compare the five candidates against the request. Use `show <id>` for full annotations and inspect the most plausible images with the available image viewer. If an asset is absent, use `download <id>` to fetch the public source on demand. For videos, extract representative frames with ffmpeg and consider motion/timing. Prefer a suitable template wherever it ranks. Offer several options if the request admits multiple interpretations; say when the library lacks a good fit. Similarity scores are not match probabilities.
4. Write short captions that map to the template's roles and preserve its joke mechanism. Captions default to English for this community; follow an explicit user request for another language. Keep all stored descriptions, aliases, scenarios, examples, and search queries in English. Explain choices to the user in their preferred language. Annotations describe creative usage, not verified historical origin.

## Caption or remix

For reviewed static layouts, run:

```bash
scripts/meme render imgflip-181913649 \
  --text 'Fix the bug' --text 'Rewrite the framework' \
  --output /absolute/path/caption.png
```

Use `show` to check box order, roles, and relative coordinates; `render ... --plan` previews the plan as JSON. Inspect the rendered image for overflow and covered expressions. An unreviewed layout needs visual review before overlay; alternatively, explicitly use `--mode top-caption` to add a white caption band. Library coordinates are editor-reviewed positions, not layout coordinates provided by Imgflip.

For character replacement or redraws, provide the original local asset to the available image-editing tool and preserve the panel sequence and role relationships. The caption renderer does not draw illustrations or render videos.

## Grow the library

Read [references/catalog.md](references/catalog.md) before editing records.

```bash
scripts/meme sync-imgflip --type both
scripts/meme pending --limit 10
scripts/meme show imgflip-181913649
scripts/meme put /absolute/path/complete-card.json
scripts/meme embed --offline
scripts/meme stats
```

Sync preserves existing annotations and layouts; it adds new templates as drafts without downloading everything. Drafts are excluded from semantic retrieval. Inspect media and complete English annotations before setting a card ready. `put` updates one card's database records; `embed --offline` encodes only new or changed documents. After direct JSON edits, run `build` then `embed --offline`.

To extend beyond the free API's top 100 per type, read [references/imgflip-collection.md](references/imgflip-collection.md). Its bounded public-HTML collector can select up to 500 unique images and 500 animated templates with robots checks, rate limits, caching, and provenance. GIF website ranking has an unspecified time window. New imports remain drafts; original media URLs are confirmed from public detail pages when `download` is requested.

Card JSON is the editable source. SQLite stores metadata and text documents; `vectors.npz` stores embeddings. Searching uses indexes rather than opening every card. Semantic retrieval does not require an exhaustive synonym dictionary. Installation, scaling limits, and candidate recall checks are in [references/retrieval.md](references/retrieval.md).

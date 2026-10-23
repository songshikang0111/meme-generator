# Catalog and incremental maintenance

Run `scripts/meme` to select the skill's Python environment. Still-image rendering requires Pillow and a suitable font; the default is DejaVu Sans Bold. Use `--font` when captions need a different character set.

```text
catalog/
  cards/<id>.json    # Canonical editable record for each template
  assets/<id>.<ext>  # Original source media; save rendered outputs elsewhere
  concepts.json     # Optional English phrase groups for lexical search only
  index.sqlite3     # Rebuildable metadata, FTS, and semantic document store
  vectors.npz       # Rebuildable vectors, model metadata, and content digests
  retrieval.json    # Default search mode and English query policy
```

`put` updates a single card. `build` reconstructs derived records and removes deleted cards. Search does not walk the cards directory. Do not put the whole catalog or media base64 in SKILL.md.

## Card schema

Use an existing ready card as a reference and submit a complete JSON object with `put`.

- `schema_version`: 1. `id`: stable `imgflip-<number>` or `local-<slug>`. Do not change IDs when rankings change.
- `name`, `aliases`: original title and English alternative names. Preserve proper names.
- `language`: `en` for the library's editorial metadata.
- `media_type`: `image` or `video`. Imported motion templates may be MP4 despite the provider's `gif` category.
- `source`: `provider`, optional `template_id`, `page_url`, `retrieved_at`, `rights`. Record provenance without treating the platform as the author or public download access as a license.
- `asset`: optional `url`, library-relative `path`, and downloaded `sha256`.
- `stats`: provider metadata; lifetime caption estimates do not measure monthly usage.
- `status`: `draft` or `ready`. Only ready cards enter semantic search.
- `annotation.summary`: concise usage description. `visual`: actual subjects, actions, and panel sequence. `mechanism`: how the humor works.
- `annotation.scenarios`: three or more concrete, transferable situations. `keywords`, `emotions`, `roles`: English concepts, emotional signals, and the meaning of each visual subject or panel.
- `annotation.examples`: `[{"texts":["caption 1","caption 2"],"why":"Why the joke works"}]`.
- `annotation.avoid`: common misuse. Excluded from embedding text to avoid retrieving a template for what it cannot express.
- `annotation.basis`: interpretation basis; distinguish visual inspection from verified historical provenance.
- `layout`: `status` (`reviewed`/`unreviewed`) and `boxes`. Each box has `x,y,w,h` in relative 0–1 coordinates and a `role`. Optional `color`, `stroke`, `stroke_color`, `align`, `rotation` (degrees clockwise). Reviewed means checked against the local image, not provided by the source API.

## Annotation workflow

1. Download on demand and inspect the image or representative video frames. Describe literal visual content before interpreting it.
2. Write a short mechanism and three to six varied scenarios in English. Avoid repeating the template title as the entire explanation or inventing its history.
3. Explain subject roles and write one or two caption sets with a rationale. For reviewed layouts, example text order must match box order.
4. Set boxes only after inspecting the source. Test a render before marking a static layout reviewed. Video cards may be ready with unreviewed layouts.
5. Submit the complete card with `put`, then run `embed --offline` to refresh changed vectors. Direct file edits require `build` first.
6. Try natural English requests that do not copy the template title. Judge whether an appropriate candidate appears among five, then inspect it. Do not tune descriptions solely to force a particular rank.

The free sync makes separate image/gif API requests, preserves existing cards, and does not crawl the website. Downloads have a 30 MB limit. Respect server errors such as 403/429 rather than bypassing them.

Sources: [Imgflip API](https://imgflip.com/api), [terms](https://imgflip.com/terms).

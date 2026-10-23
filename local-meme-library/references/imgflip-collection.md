# Extending beyond the free top 100

## Findings and scope

The [free API](https://imgflip.com/api) documents `get_memes`, with a `type` filter and no documented pagination or limit parameter. Its documentation describes roughly 100 results ordered by recent 30-day caption activity, while reserving the right to change the size and order. `get_meme` by ID and `search_memes` are Premium endpoints. Collecting public IDs does not make either endpoint free. The current Premium base price is $9.99/month; no subscription or paid request was used here.

The public [template listing](https://imgflip.com/memetemplates) has ordinary next-page links and an active **Top 30 days** selector. Each page currently contains 40 cards. It mixes images and animated templates beyond the initial results, so the collector filters on visible animation labels and GIF-maker links before selecting 500 unique images. It does not treat the first 500 mixed entries as 500 still images.

The separate [GIF listing](https://imgflip.com/gif-templates) also has public pagination. Its ranking is described as popular, but the page does not state a time window. Even a strong overlap with the free API's first 100 would be evidence about the current ordering, not proof that the whole GIF website list is a 30-day ranking. Store it as `public_popular_listing_unspecified_time_window`.

At inspection on 2026-10-23, [robots.txt](https://imgflip.com/robots.txt) disallowed `/orig/` and `/browse/`, with no disallow rule for these listing or template-detail paths. The collector checks the current rules before each run. Robots rules indicate crawler preferences; they do not grant image rights. [Imgflip's terms](https://imgflip.com/terms) retain applicable intellectual property requirements and prohibit service misuse. This workflow reads ordinary public interfaces and does not claim a redistribution license for the collected media.

## Reproducible bounded collection

From the skill directory:

```bash
python3 scripts/collect_imgflip.py --per-type 500 --delay 3
```

The script follows only same-origin next links, with one active request and a default minimum three-second start interval. It identifies itself, checks robots rules, caches successful pages for 24 hours, deduplicates IDs, and caps each type at 20 pages and 500 selected records. It stops on HTTP errors, redirects, access challenges, unexpected markup, or ID conflicts. There are no automatic retries, login attempts, proxy rotation, or calls to undocumented/premium endpoints. A resumed run uses cached successful pages.

The two groups must be collected and prevalidated before import. Existing annotations, layouts, names, downloaded assets, and API metadata are preserved. New records are drafts. No source images or videos are bulk-downloaded.

## Snapshot and evidence

- `catalog/collections/imgflip-public-listings.json`: selected IDs, names, previews, detail links, page hashes, retrieval times, listing positions, and per-type positions.
- `catalog/collections/imgflip-api-crosscheck.json`: observed overlap with a fresh free-API top 100 for each type. This is a separate observation, not the source of entries beyond 100.
- `.runtime/imgflip-listings/`: ignored raw HTML/policy cache. Page hashes allow matching the cache to the tracked manifest.

The initial successful snapshot selected 500 images from 14 pages and 500 animated templates from 13 pages, yielding 1,000 distinct IDs. Image filtering skipped 37 animated entries and 6 duplicate appearances before the 500th unique image, which appeared at mixed-list position 543. The GIF selection reached 500 unique records at position 500. Duplicates and gaps can occur because web pages may be cached or ranks may move between requests. These are timestamped observations rather than an atomic authoritative ranking export.

The catalog grew from 200 to 1,000 records, preserving all 30 ready cards. The 800 new cards need media inspection and English annotations before entering semantic retrieval.

## Source media on demand

HTML lists expose thumbnails, not complete API metadata. Do not use thumbnail dimensions as original dimensions, or a GIF poster as video. A filename's base36 code supplies an ID when a numeric page link is absent; numeric links and encoded IDs must agree when both exist.

For new cards, `asset.preview_url` records the actual public thumbnail. `asset.original_url_candidate` is a pattern-derived candidate kept for provenance; it is not assigned to `asset.url` or automatically trusted. Width, height, box count, caption statistics, and historical origin remain unknown unless obtained from an appropriate source.

`meme download <id>` resolves a card without `asset.url` through its ordinary `/memetemplate/<id>` page. It reads the explicit original image element or MP4 source, validates the media host and encoded ID, and records the detail URL, time, and hash. This lookup uses the same robots-aware, cached, low-frequency client. The subsequent media download is delayed, bounded to 30 MB, and never substitutes a poster for a video. Actual downloads of a new image and a new MP4 beyond the original API set have been verified.

Follow the normal annotation process in [catalog.md](catalog.md), then run `put` and `embed --offline`. Expanding draft metadata alone does not change semantic search coverage.

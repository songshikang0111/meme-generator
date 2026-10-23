# Runtime and model provenance

Default model: [sentence-transformers/all-MiniLM-L6-v2](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2), revision `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`. The model card labels it English and Apache-2.0 licensed. It produces 384-dimensional text embeddings and defaults to a 256-wordpiece input limit. This model license does not grant rights to source meme images.

Runtime uses Python 3.12, CPU PyTorch, Sentence Transformers, NumPy, and Pillow. Exact direct dependency versions are in `requirements-embedding.txt` and `scripts/setup_embeddings.sh`. Setup installs CPU PyTorch from its official package index. Downloads use ordinary HTTPS; Xet transport is disabled to avoid proxy incompatibilities. No account or paid API is configured.

Weights are downloaded from a pinned Hugging Face revision as safetensors. Loading sets `trust_remote_code=False` and `local_files_only=True`. The query path is a physical local directory. Vector files use NumPy NPZ with pickle loading disabled. Live integration checks block socket connections during a cold model load and queries.

All annotations and queries are English. Multilingual instructions are translated by the calling agent before retrieval; the embedding model is not asked to understand untranslated Chinese requests.

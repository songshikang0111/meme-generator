#!/usr/bin/env bash
set -euo pipefail
skill_dir="$(cd -- "$(dirname -- "$(readlink -f -- "$0")")/.." && pwd)"
command -v uv >/dev/null || { echo 'Install uv first, or manually create a Python 3.12 environment.' >&2; exit 1; }
uv venv --python 3.12 --allow-existing "$skill_dir/.venv"
uv pip install --python "$skill_dir/.venv/bin/python" 'torch==2.14.1+cpu' --index-url https://download.pytorch.org/whl/cpu
uv pip install --python "$skill_dir/.venv/bin/python" -r "$skill_dir/requirements-embedding.txt"
"$skill_dir/scripts/meme" build
"$skill_dir/scripts/meme" embed

#!/bin/bash
# Creates jobbot/.venv (gitignored) with the bot's dependencies.
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m venv .venv
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -r requirements.txt
.venv/bin/python -c "import telegram, yaml, pypdf, certifi; print('venv OK: python-telegram-bot', telegram.__version__, '/ PyYAML', yaml.__version__, '/ pypdf', pypdf.__version__, '/ certifi', certifi.__version__)"

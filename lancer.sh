#!/usr/bin/env sh
# Lance Autoclique IA sous Linux ou macOS (installe les dépendances au premier lancement).
set -e
cd "$(dirname "$0")"

if [ ! -x .venv/bin/python ]; then
    echo "Premier lancement : installation de l'environnement Python…"
    python3 -m venv .venv
    .venv/bin/python -m pip install --upgrade pip
    .venv/bin/python -m pip install -r requirements.txt
fi

exec .venv/bin/python -m autoclique "$@"

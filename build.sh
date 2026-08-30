#!/usr/bin/env bash
# Render build script — runs during the build phase (before preDeployCommand)
set -o errexit

pip install --upgrade pip
pip install -r requirements.txt

python manage.py collectstatic --noinput

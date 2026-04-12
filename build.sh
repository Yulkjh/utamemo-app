#!/usr/bin/env bash
# exit on error
set -o errexit

pip install -r requirements.txt

cd myproject
python manage.py collectstatic --no-input
python manage.py migrate --run-syncdb

# 非公開かつ2ヶ月以上再生されていない楽曲を自動クリーンアップ
python manage.py cleanup_inactive_songs

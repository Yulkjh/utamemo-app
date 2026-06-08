#!/usr/bin/env bash
# exit on error
set -o errexit

pip install -r requirements.txt

cd myproject
python manage.py collectstatic --no-input
python manage.py migrate --run-syncdb

# Renderデプロイ時に指定ユーザーをstaff化（存在しない場合はスキップ）
if [ -n "${AUTO_MAKE_STAFF_USERNAME:-}" ]; then
	python manage.py make_staff "$AUTO_MAKE_STAFF_USERNAME" || true
fi

if [ "${SKIP_POST_DEPLOY_TASKS:-false}" != "true" ]; then
	# 非公開かつ2ヶ月以上再生されていない楽曲を自動クリーンアップ
	python manage.py cleanup_inactive_songs

	# レビューデータの自動バックアップ
	python manage.py backup_reviews || true

	# 学習データをJSONからDBにインポート（初回デプロイ用、冪等）
	python manage.py import_training_data || true
fi

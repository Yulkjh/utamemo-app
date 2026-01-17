from django.apps import AppConfig
import sys
import os


class SongsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'songs'
    
    def ready(self):
        """App startup"""
        # マイグレーション中はqueue_managerを初期化しない
        if 'makemigrations' in sys.argv or 'migrate' in sys.argv:
            print("[INFO] Skipping queue manager during migration")
            return
        
        # テスト実行中はスキップ
        if 'test' in sys.argv:
            print("[INFO] Skipping queue manager during tests")
            return
        
        # RUN_MAINはDjangoのリローダーが設定する環境変数
        # メインプロセスでのみワーカーを起動（リローダープロセスではスキップ）
        if os.environ.get('RUN_MAIN') != 'true':
            # Gunicorn/uWSGIでは最初のワーカーのみで実行
            # DYNOやWORKER_IDなどをチェックしてプライマリワーカーを特定
            worker_id = os.environ.get('GUNICORN_WORKER_ID', os.environ.get('DYNO', ''))
            
            # 開発環境ではRUN_MAINが設定されない場合があるので、
            # runserverコマンドの場合は許可
            if 'runserver' not in sys.argv and not worker_id:
                print("[INFO] Skipping queue manager (not main process)")
                return
        
        # 環境変数でキューワーカーを無効化できるようにする
        if os.environ.get('DISABLE_QUEUE_WORKER', 'false').lower() == 'true':
            print("[INFO] Queue worker disabled by environment variable")
            return
            
        # キューマネージャーを初期化（ワーカースレッドを開始）
        try:
            from .queue_manager import queue_manager
            print("[INFO] キューマネージャーを初期化しました")
        except Exception as e:
            print(f"[WARNING] キューマネージャーの初期化エラー: {e}")

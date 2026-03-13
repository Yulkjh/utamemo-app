from django.apps import AppConfig
import sys
import os
import logging

logger = logging.getLogger(__name__)


class SongsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'songs'
    
    def ready(self):
        """App startup"""
        # マイグレーション中はqueue_managerを初期化しない
        if 'makemigrations' in sys.argv or 'migrate' in sys.argv:
            logger.info("Skipping queue manager during migration")
            return
        
        # テスト実行中はスキップ
        if 'test' in sys.argv:
            logger.info("Skipping queue manager during tests")
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
                logger.info("Skipping queue manager (not main process)")
                return
        
        # 環境変数でキューワーカーを無効化できるようにする
        if os.environ.get('DISABLE_QUEUE_WORKER', 'false').lower() == 'true':
            logger.info("Queue worker disabled by environment variable")
            return
            
        # キューマネージャーを初期化（ワーカースレッドを開始）
        try:
            from .queue_manager import queue_manager
            logger.info("キューマネージャーを初期化しました")
            
            # 起動時にスタックしたキューをクリーンアップ
            self._cleanup_stale_queue()
        except Exception as e:
            logger.warning(f"キューマネージャーの初期化エラー: {e}")

    def _cleanup_stale_queue(self):
        """起動時にスタックしたキューをクリーンアップ"""
        try:
            from .models import Song
            
            # 完了/失敗なのにqueue_positionが残っている曲をクリア
            stale = Song.objects.filter(
                generation_status__in=['completed', 'failed'],
                queue_position__isnull=False
            )
            stale_count = stale.count()
            if stale_count > 0:
                stale.update(queue_position=None)
                logger.info(f"起動時クリーンアップ: {stale_count}曲のスタックしたqueue_positionをクリア")
            
            # 1時間以上generating状態の曲をfailedに
            from django.utils import timezone
            from datetime import timedelta
            cutoff = timezone.now() - timedelta(hours=1)
            
            stuck_generating = Song.objects.filter(
                generation_status='generating',
                started_at__lt=cutoff
            )
            stuck_count = stuck_generating.count()
            if stuck_count > 0:
                stuck_generating.update(
                    generation_status='failed',
                    queue_position=None,
                    error_message='サーバー再起動によりリセットされました。再生成してください。'
                )
                logger.info(f"起動時クリーンアップ: {stuck_count}曲のスタックしたgenerating曲をfailedに変更")

            # queue_positionを再計算
            active_songs = Song.objects.filter(
                generation_status__in=['pending', 'generating']
            ).order_by('created_at')
            for index, song in enumerate(active_songs, start=1):
                if song.queue_position != index:
                    song.queue_position = index
                    song.save(update_fields=['queue_position'])
            
            logger.info(f"起動時クリーンアップ完了（アクティブキュー: {active_songs.count()}曲）")
        except Exception as e:
            logger.warning(f"起動時キュークリーンアップエラー: {e}")

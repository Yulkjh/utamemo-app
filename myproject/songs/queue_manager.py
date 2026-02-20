"""曲生成キュー管理システム"""
import threading
import time
import logging
from django.db import transaction
from django.utils import timezone
from django.conf import settings
from .models import Song

# ロギング設定
logger = logging.getLogger(__name__)


def send_progress_update(song_id, status, progress, message, audio_url=None):
    """WebSocket経由で進捗更新を送信（ノンブロッキング、メイン処理を中断しない）"""
    try:
        from asgiref.sync import async_to_sync
        from channels.layers import get_channel_layer
        
        channel_layer = get_channel_layer()
        if channel_layer:
            async_to_sync(channel_layer.group_send)(
                f'song_{song_id}_progress',
                {
                    'type': 'song_progress',
                    'status': status,
                    'progress': progress,
                    'message': message,
                    'audio_url': audio_url,
                }
            )
            logger.debug(f"WebSocket progress sent: Song {song_id} - {status} ({progress}%)")
    except Exception as e:
        # WebSocketエラーは曲生成を中断しない
        logger.debug(f"WebSocket update skipped (non-critical): {e}")


class SongGenerationQueue:
    """曲生成キューのシングルトン"""
    _instance = None
    _lock = threading.Lock()
    _processing = False
    _processing_lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not hasattr(self, 'initialized'):
            self.initialized = True
            self._start_worker()
    
    def _start_worker(self):
        """自動復旧機能付きのバックグラウンドワーカースレッドを開始"""
        self._worker_thread = None
        self._should_run = True
        self._start_worker_thread()
    
    def _start_worker_thread(self):
        """ワーカースレッドを開始または再起動"""
        self._worker_thread = threading.Thread(target=self._worker_wrapper, daemon=True)
        self._worker_thread.start()
        logger.info("Queue worker thread started")
    
    def _worker_wrapper(self):
        """クラッシュ時の自動復旧付きワーカーラッパー"""
        while self._should_run:
            try:
                self._process_queue()
            except Exception as e:
                logger.critical(f"Worker crashed unexpectedly: {e}", exc_info=True)
                # 再起動前に待機
                time.sleep(10)
                logger.info("Attempting to restart worker...")
    
    def add_to_queue(self, song_id, lyrics_content, title, genre, vocal_style='female'):
        """曲をキューに追加"""
        logger.info(f"Song {song_id} added to queue (vocal: {vocal_style})")
        # 曲のステータスは既にpendingに設定済み
        # ワーカースレッドが自動的に処理
        
        # ワーカーの健全性をチェックし、必要に応じて再起動
        self._check_worker_health()
    
    def _check_worker_health(self):
        """ワーカースレッドが生きているかチェックし、必要なら再起動"""
        if self._worker_thread is None or not self._worker_thread.is_alive():
            logger.warning("Worker thread not running, restarting...")
            self._start_worker_thread()
    
    def _process_queue(self):
        """キューワーカー"""
        poll_interval = getattr(settings, 'QUEUE_POLL_INTERVAL', 5)
        logger.info(f"Queue worker processing started (poll interval: {poll_interval}s)")
        
        while self._should_run:
            try:
                # スタックしたgenerating曲をタイムアウト（5分超過でfailed）
                self._timeout_stuck_songs()
                
                # 処理中フラグをチェック
                with self._processing_lock:
                    if self._processing:
                        time.sleep(poll_interval)
                        continue
                    
                    # 次の処理対象の曲を取得
                    with transaction.atomic():
                        pending_song = Song.objects.select_for_update().filter(
                            generation_status='pending'
                        ).order_by('created_at').first()
                        
                        if pending_song:
                            # 処理開始
                            pending_song.generation_status = 'generating'
                            pending_song.started_at = timezone.now()
                            pending_song.error_message = None  # 前回のエラーをクリア
                            pending_song.save()
                            self._processing = True
                            song_id = pending_song.id
                            # WebSocket更新を送信
                            send_progress_update(song_id, 'generating', 20, '生成を開始しています...')
                        else:
                            song_id = None
                
                if song_id:
                    logger.info(f"Starting generation for Song {song_id}")
                    try:
                        self._generate_song(song_id)
                    except Exception as e:
                        error_msg = str(e)
                        logger.error(f"Error generating Song {song_id}: {error_msg}", exc_info=True)
                        # エラー時にステータスを更新
                        try:
                            with transaction.atomic():
                                song = Song.objects.select_for_update().get(id=song_id)
                                song.generation_status = 'failed'
                                song.queue_position = None
                                song.error_message = error_msg[:1000]  # エラーメッセージの長さを制限
                                song.save()
                        except Exception:
                            pass
                    finally:
                        with self._processing_lock:
                            self._processing = False
                        logger.info(f"Completed processing Song {song_id}")
                        
                        # キューの位置を更新
                        self._update_queue_positions()
                else:
                    # キューが空なら待機
                    time.sleep(poll_interval)
                    
            except Exception as e:
                logger.error(f"Queue worker error: {e}", exc_info=True)
                with self._processing_lock:
                    self._processing = False
                time.sleep(poll_interval)
    
    def _generate_song(self, song_id):
        """リトライロジックとエラー追跡付きの曲生成"""
        from datetime import timedelta
        from .ai_services import MurekaAIGenerator
        
        max_retries = getattr(settings, 'MAX_GENERATION_RETRIES', 3)
        backoff_base = getattr(settings, 'RETRY_BACKOFF_BASE', 5)  # 5秒（30秒→5秒に短縮）
        retry_count = 0
        last_error = None
        
        try:
            # Songオブジェクトを取得
            song = Song.objects.get(id=song_id)
            
            # 歌詞を取得
            if not hasattr(song, 'lyrics') or not song.lyrics:
                error_msg = "歌詞がありません"
                logger.error(f"Song {song_id}: {error_msg}")
                song.generation_status = 'failed'
                song.error_message = error_msg
                song.save()
                return
            
            lyrics_content = song.lyrics.content
            if not lyrics_content or len(lyrics_content.strip()) < 10:
                error_msg = "歌詞が短すぎるか空です"
                logger.error(f"Song {song_id}: {error_msg}")
                song.generation_status = 'failed'
                song.error_message = error_msg
                song.save()
                return
                
            title = song.title or 'Untitled'
            genre = song.genre or 'pop'
            vocal_style = song.vocal_style or 'female'
            music_prompt = getattr(song, 'music_prompt', '') or ''
            reference_song = getattr(song, 'reference_song', '') or ''

            from .ai_services import convert_lyrics_to_hiragana_with_context, detect_lyrics_language
            logger.info(f"Song {song_id}: Original lyrics length: {len(lyrics_content)} chars")
            
            # 歌詞の言語を判定
            lyrics_language = detect_lyrics_language(lyrics_content)
            logger.info(f"Song {song_id}: Detected lyrics language: {lyrics_language}")
            
            # 日本語の場合のみひらがな変換（中国語・英語等はそのまま送信）
            if lyrics_language == 'ja':
                send_progress_update(song_id, 'generating', 25, '歌詞を処理中...')
                try:
                    hiragana_lyrics = convert_lyrics_to_hiragana_with_context(lyrics_content)
                except Exception as e:
                    logger.warning(f"Song {song_id}: Hiragana conversion failed: {e}")
                    hiragana_lyrics = lyrics_content
                    
                logger.info(f"Song {song_id}: After hiragana conversion: {len(hiragana_lyrics)} chars")
                
                # 変換後の長さが大幅に増加した場合は警告
                if len(hiragana_lyrics) > len(lyrics_content) * 1.5:
                    logger.warning(f"Song {song_id}: Lyrics expanded significantly after hiragana conversion")
            else:
                logger.info(f"Song {song_id}: Skipping hiragana conversion for {lyrics_language} lyrics")
                send_progress_update(song_id, 'generating', 25, '歌詞を処理中...')
                hiragana_lyrics = lyrics_content

            while retry_count < max_retries:
                try:
                    logger.info(f"Song {song_id}: Starting generation (Attempt {retry_count + 1}/{max_retries})")
                    
                    # 進捗更新を送信 - API呼び出し開始
                    send_progress_update(song_id, 'generating', 40, f'Mureka APIで生成中... (試行 {retry_count + 1}/{max_retries})')
                    
                    mureka_generator = MurekaAIGenerator()
                    
                    if not mureka_generator.use_real_api:
                        error_msg = "Mureka APIが設定されていません"
                        logger.error(f"Song {song_id}: {error_msg}")
                        raise Exception(error_msg)
                    
                    song_result = mureka_generator.generate_song(
                        lyrics=hiragana_lyrics,
                        title=title,
                        genre=genre.lower() if genre else 'pop',
                        vocal_style=vocal_style,
                        model=song.mureka_model or 'mureka-v8',
                        music_prompt=music_prompt,
                        reference_song=reference_song
                    )
                    
                    logger.info(f"Song {song_id}: Generation result: {song_result}")
                    
                    # 結果を保存
                    if song_result and (song_result.get('status') == 'completed' or song_result.get('audio_url')):
                        logger.info(f"Song {song_id}: Generation successful")
                        
                        # 進捗更新を送信 - 結果処理中
                        send_progress_update(song_id, 'processing', 80, '生成結果を処理中...')
                        
                        # 曲の情報を更新
                        song.refresh_from_db()
                        duration_seconds = song_result.get('duration', 180)
                        try:
                            song.duration = timedelta(seconds=duration_seconds / 1000) if duration_seconds > 1000 else timedelta(seconds=duration_seconds)
                        except Exception:
                            song.duration = timedelta(seconds=180)
                        
                        audio_url = song_result.get('audio_url')
                        if audio_url:
                            song.audio_url = audio_url
                        
                        song.generation_status = 'completed'
                        song.completed_at = timezone.now()
                        song.queue_position = None
                        song.error_message = None  # 前回のエラーをクリア
                        song.save()
                        logger.info(f"Song {song_id}: Saved with audio_url: {audio_url}")
                        
                        # アップロード画像を削除（生成完了後）
                        if song.source_image:
                            try:
                                source_image = song.source_image
                                # ファイルを削除
                                if source_image.image:
                                    source_image.image.delete(save=False)
                                # DBレコードを削除
                                source_image.delete()
                                logger.info(f"Song {song_id}: Source image deleted after completion")
                            except Exception as img_error:
                                logger.warning(f"Song {song_id}: Failed to delete source image: {img_error}")
                        
                        # 完了更新を送信
                        send_progress_update(song_id, 'completed', 100, '生成完了！', audio_url)
                        
                        return  # 成功、終了
                    else:
                        raise Exception("曲生成が有効な結果を返しませんでした")
                        
                except Exception as e:
                    last_error = str(e)
                    retry_count += 1
                    logger.warning(f"Song {song_id}: Attempt {retry_count} failed: {last_error}")
                    
                    if retry_count < max_retries:
                        wait_time = backoff_base * retry_count  # 指数バックオフ
                        logger.info(f"Song {song_id}: Waiting {wait_time}s before retry")
                        time.sleep(wait_time)
                        try:
                            song.refresh_from_db()  # 変更があった場合に再取得
                        except Exception:
                            pass
                    else:
                        logger.error(f"Song {song_id}: All {max_retries} attempts failed")
            
            # すべてのリトライが失敗
            logger.error(f"Song {song_id}: Generation failed after {max_retries} attempts: {last_error}")
            song.refresh_from_db()
            song.generation_status = 'failed'
            song.queue_position = None
            song.error_message = f"Failed after {max_retries} attempts: {last_error}"[:1000]
            song.save()
            
            # 失敗更新を送信
            send_progress_update(song_id, 'failed', 0, f'生成失敗: {last_error[:100]}')
                
        except Song.DoesNotExist:
            logger.error(f"Song {song_id}: Not found")
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Song {song_id}: _generate_song error: {error_msg}", exc_info=True)
            # 最終的にfailedに設定
            try:
                song = Song.objects.get(id=song_id)
                song.generation_status = 'failed'
                song.queue_position = None
                song.error_message = error_msg[:1000]
                song.save()
            except Exception:
                pass
    
    def _timeout_stuck_songs(self):
        """5分以上generating状態の曲をfailedに変更"""
        try:
            from datetime import timedelta
            cutoff = timezone.now() - timedelta(minutes=5)
            stuck = Song.objects.filter(
                generation_status='generating',
                started_at__lt=cutoff
            )
            for song in stuck:
                elapsed = (timezone.now() - song.started_at).total_seconds()
                logger.warning(f"Song {song.id}: Stuck in generating for {int(elapsed)}s, marking as failed")
                song.generation_status = 'failed'
                song.queue_position = None
                song.error_message = f'生成がタイムアウトしました（{int(elapsed)}秒経過）。再生成してください。'
                song.save()
        except Exception as e:
            logger.warning(f"Timeout check error: {e}")

    def _update_queue_positions(self):
        """キューの位置を更新（完了/失敗した曲のposition もクリア）"""
        try:
            # まず完了・失敗した曲のqueue_positionをクリア
            stale_songs = Song.objects.filter(
                generation_status__in=['completed', 'failed'],
                queue_position__isnull=False
            )
            if stale_songs.exists():
                count = stale_songs.update(queue_position=None)
                logger.info(f"Cleared stale queue positions for {count} completed/failed songs")
            
            # pending/generating の曲だけ位置を再計算
            pending_songs = Song.objects.filter(
                generation_status__in=['pending', 'generating']
            ).order_by('created_at')
            
            for index, song in enumerate(pending_songs, start=1):
                if song.queue_position != index:
                    song.queue_position = index
                    song.save(update_fields=['queue_position'])
                    
            logger.debug(f"Queue updated: {pending_songs.count()} songs pending")
        except Exception as e:
            logger.warning(f"Queue position update error: {e}")


# グローバルインスタンス
queue_manager = SongGenerationQueue()

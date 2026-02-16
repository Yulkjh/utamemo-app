"""楽曲生成キュー管理システム"""
import threading
import time
from django.db import transaction
from songs.models import Song


class SongGenerationQueue:
    """楽曲生成キューを管理するシングルトンクラス"""
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
        """バックグラウンドワーカースレッドを開始"""
        worker_thread = threading.Thread(target=self._process_queue, daemon=True)
        worker_thread.start()
        print("[INFO] Queue worker started")
    
    def add_to_queue(self, song_id, lyrics_content, title, genre, vocal_style='female'):
        """楽曲をキューに追加"""
        print(f"[INFO] Added Song ID {song_id} to queue with vocal style: {vocal_style}")
    
    def _process_queue(self):
        """キューを処理するワーカー"""
        print("[INFO] Queue worker processing started")
        
        while True:
            try:
                with self._processing_lock:
                    if self._processing:
                        time.sleep(5)
                        continue
                    
                    with transaction.atomic():
                        pending_song = Song.objects.select_for_update().filter(
                            generation_status='pending'
                        ).order_by('created_at').first()
                        
                        if pending_song:
                            pending_song.generation_status = 'generating'
                            pending_song.save()
                            self._processing = True
                            song_id = pending_song.id
                        else:
                            song_id = None
                
                if song_id:
                    print(f"[INFO] Starting generation for Song ID {song_id}")
                    try:
                        self._generate_song(song_id)
                    except Exception as e:
                        print(f"[ERROR] Error generating Song ID {song_id}: {e}")
                        import traceback
                        traceback.print_exc()
                        try:
                            with transaction.atomic():
                                song = Song.objects.select_for_update().get(id=song_id)
                                song.generation_status = 'failed'
                                song.queue_position = None
                                song.save()
                        except:
                            pass
                    finally:
                        with self._processing_lock:
                            self._processing = False
                        print(f"[INFO] Completed processing Song ID {song_id}")
                        
                        self._update_queue_positions()
                else:
                    time.sleep(5)
                    
            except Exception as e:
                print(f"[ERROR] Queue worker error: {e}")
                import traceback
                traceback.print_exc()
                with self._processing_lock:
                    self._processing = False
                time.sleep(5)
    
    def _generate_song(self, song_id):
        """実際の楽曲生成処理"""
        from datetime import timedelta
        from songs.ai_services import GeminiLyricsGenerator, MurekaAIGenerator
        
        try:
            song = Song.objects.get(id=song_id)
            
            if not hasattr(song, 'lyrics') or not song.lyrics:
                print(f"[ERROR] Song ID {song_id} has no lyrics")
                song.generation_status = 'failed'
                song.save()
                return
            
            lyrics_content = song.lyrics.content
            title = song.title
            genre = song.genre or 'pop'
            vocal_style = song.vocal_style or 'female'
            
            print(f"[INFO] Converting lyrics to hiragana...")
            lyrics_generator = GeminiLyricsGenerator()
            hiragana_lyrics = lyrics_generator.convert_to_hiragana(lyrics_content)
            print(f"[INFO] Hiragana conversion complete")
            
            print(f"[INFO] Starting song generation with Mureka API...")
            mureka_generator = MurekaAIGenerator()
            song_result = mureka_generator.generate_song(
                lyrics=hiragana_lyrics,
                title=title,
                genre=genre.lower()
            )
            
            print(f"[INFO] Song generation result: {song_result}")
            
            if song_result and (song_result.get('status') == 'completed' or song_result.get('audio_url')):
                print(f"[INFO] Song generation successful")
                
                song.refresh_from_db()
                duration_seconds = song_result.get('duration', 180)
                song.duration = timedelta(seconds=duration_seconds / 1000) if duration_seconds > 1000 else timedelta(seconds=duration_seconds)
                
                audio_url = song_result.get('audio_url')
                if audio_url:
                    song.audio_url = audio_url
                
                song.generation_status = 'completed'
                song.queue_position = None
                song.save()
                print(f"[INFO] Song saved: {audio_url}")
                
                # アップロード画像を削除（生成完了後）
                if song.source_image:
                    try:
                        source_image = song.source_image
                        if source_image.image:
                            source_image.image.delete(save=False)
                        source_image.delete()
                        print(f"[INFO] Source image deleted for song {song.id}")
                    except Exception as img_error:
                        print(f"[WARNING] Failed to delete source image: {img_error}")
            else:
                print(f"[ERROR] Song generation failed")
                song.generation_status = 'failed'
                song.queue_position = None
                song.save()
                
        except Exception as e:
            print(f"[ERROR] _generate_song error: {e}")
            import traceback
            traceback.print_exc()
            raise
    
    def _update_queue_positions(self):
        """キュー内の曲の位置を更新（完了/失敗した曲のposition もクリア）"""
        try:
            # まず完了・失敗した曲のqueue_positionをクリア
            stale_songs = Song.objects.filter(
                generation_status__in=['completed', 'failed'],
                queue_position__isnull=False
            )
            if stale_songs.exists():
                count = stale_songs.update(queue_position=None)
                print(f"[INFO] Cleared stale queue positions for {count} completed/failed songs")
            
            # pending/generating の曲だけ位置を再計算
            pending_songs = Song.objects.filter(
                generation_status__in=['pending', 'generating']
            ).order_by('created_at')
            
            for index, song in enumerate(pending_songs, start=1):
                if song.queue_position != index:
                    song.queue_position = index
                    song.save(update_fields=['queue_position'])
                    
            print(f"[INFO] Queue updated: {pending_songs.count()} songs pending")
        except Exception as e:
            print(f"[WARNING] Queue position update error: {e}")


queue_manager = SongGenerationQueue()

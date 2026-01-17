import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from .models import Song


class SongProgressConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.song_id = self.scope['url_route']['kwargs']['song_id']
        self.room_group_name = f'song_{self.song_id}_progress'

        # グループに参加
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )

        await self.accept()

        # 接続時に現在の状態を送信
        song_status = await self.get_song_status()
        await self.send(text_data=json.dumps(song_status))

    async def disconnect(self, close_code):
        # グループから離脱
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )

    async def receive(self, text_data):
        # クライアントからのステータス確認リクエスト
        data = json.loads(text_data)
        if data.get('type') == 'check_status':
            song_status = await self.get_song_status()
            await self.send(text_data=json.dumps(song_status))

    async def song_progress(self, event):
        # グループから進捗更新を受信してクライアントに送信
        await self.send(text_data=json.dumps({
            'type': 'progress_update',
            'status': event['status'],
            'progress': event['progress'],
            'message': event['message'],
            'audio_url': event.get('audio_url', None),
        }))

    @database_sync_to_async
    def get_song_status(self):
        try:
            song = Song.objects.get(id=self.song_id)
            status_messages = {
                'pending': 'キューで待機中...',
                'processing': '楽曲を生成中...',
                'completed': '生成完了！',
                'failed': '生成に失敗しました',
            }
            
            progress_values = {
                'pending': 10,
                'processing': 50,
                'completed': 100,
                'failed': 0,
            }
            
            return {
                'type': 'status_update',
                'status': song.generation_status,
                'progress': progress_values.get(song.generation_status, 0),
                'message': status_messages.get(song.generation_status, '状態を確認中...'),
                'audio_url': song.audio_url if song.audio_url else None,
                'queue_position': song.queue_position,
            }
        except Song.DoesNotExist:
            return {
                'type': 'error',
                'status': 'error',
                'progress': 0,
                'message': '楽曲が見つかりません',
            }

from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.db import IntegrityError
from .models import Song, Lyrics, Tag, Like, Favorite
from .content_filter import check_text_for_inappropriate_content

User = get_user_model()


class SongModelTest(TestCase):
    """Songモデルの基本テスト"""
    
    def setUp(self):
        self.user = User.objects.create_user(username='testuser', password='testpass123')
    
    def test_song_creation(self):
        """曲が正しく作成されること"""
        song = Song.objects.create(
            title='テスト曲',
            artist='テストアーティスト',
            genre='pop',
            created_by=self.user,
        )
        self.assertEqual(song.title, 'テスト曲')
        self.assertEqual(song.created_by, self.user)
    
    def test_song_str(self):
        """曲の__str__が正しいこと"""
        song = Song.objects.create(title='テスト曲', created_by=self.user)
        self.assertIn('テスト曲', str(song))
    
    def test_song_default_values(self):
        """曲のデフォルト値が正しいこと"""
        song = Song.objects.create(title='テスト曲', created_by=self.user)
        self.assertFalse(song.is_public)
        self.assertFalse(song.is_encrypted)
        self.assertEqual(song.generation_status, 'pending')
        self.assertEqual(song.likes_count, 0)
        self.assertEqual(song.total_plays, 0)
    
    def test_song_ordering(self):
        """曲が作成日時の降順で並ぶこと"""
        song1 = Song.objects.create(title='曲1', created_by=self.user)
        song2 = Song.objects.create(title='曲2', created_by=self.user)
        songs = list(Song.objects.all())
        self.assertEqual(songs[0], song2)
        self.assertEqual(songs[1], song1)


class LyricsModelTest(TestCase):
    """Lyricsモデルの基本テスト"""
    
    def setUp(self):
        self.user = User.objects.create_user(username='testuser', password='testpass123')
        self.song = Song.objects.create(title='テスト曲', created_by=self.user)
    
    def test_lyrics_creation(self):
        """歌詞が正しく作成されること"""
        lyrics = Lyrics.objects.create(
            song=self.song,
            content='テスト歌詞',
            original_text='テスト原文',
        )
        self.assertEqual(lyrics.song, self.song)
        self.assertEqual(lyrics.content, 'テスト歌詞')
    
    def test_lyrics_str(self):
        """歌詞の__str__が正しいこと"""
        lyrics = Lyrics.objects.create(song=self.song, content='テスト歌詞')
        self.assertIn('テスト曲', str(lyrics))


class TagModelTest(TestCase):
    """Tagモデルの基本テスト"""
    
    def test_tag_creation(self):
        """タグが正しく作成されること"""
        tag = Tag.objects.create(name='テストタグ')
        self.assertEqual(str(tag), '#テストタグ')
    
    def test_tag_unique(self):
        """同名タグが重複作成されないこと"""
        Tag.objects.create(name='ユニーク')
        with self.assertRaises(IntegrityError):
            Tag.objects.create(name='ユニーク')


class LikeAndFavoriteTest(TestCase):
    """いいね・お気に入り機能のテスト"""
    
    def setUp(self):
        self.user = User.objects.create_user(username='testuser', password='testpass123')
        self.song = Song.objects.create(title='テスト曲', created_by=self.user, generation_status='completed')
        self.client = Client()
        self.client.login(username='testuser', password='testpass123')
    
    def test_like_song(self):
        """曲にいいねできること"""
        like = Like.objects.create(user=self.user, song=self.song)
        self.assertEqual(Like.objects.filter(user=self.user, song=self.song).count(), 1)
    
    def test_like_unique_constraint(self):
        """同じユーザーが同じ曲に2回いいねできないこと"""
        Like.objects.create(user=self.user, song=self.song)
        with self.assertRaises(IntegrityError):
            Like.objects.create(user=self.user, song=self.song)
    
    def test_unlike_song(self):
        """いいねを取り消せること"""
        like = Like.objects.create(user=self.user, song=self.song)
        like.delete()
        self.assertEqual(Like.objects.filter(user=self.user, song=self.song).count(), 0)
    
    def test_favorite_song(self):
        """曲をお気に入りに追加できること"""
        fav = Favorite.objects.create(user=self.user, song=self.song)
        self.assertEqual(Favorite.objects.filter(user=self.user, song=self.song).count(), 1)
    
    def test_favorite_unique_constraint(self):
        """同じユーザーが同じ曲を2回お気に入りできないこと"""
        Favorite.objects.create(user=self.user, song=self.song)
        with self.assertRaises(IntegrityError):
            Favorite.objects.create(user=self.user, song=self.song)
    
    def test_unfavorite_song(self):
        """お気に入りを解除できること"""
        fav = Favorite.objects.create(user=self.user, song=self.song)
        fav.delete()
        self.assertEqual(Favorite.objects.filter(user=self.user, song=self.song).count(), 0)


class SongViewTest(TestCase):
    """曲関連ビューのテスト"""
    
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='testuser', password='testpass123')
        self.song = Song.objects.create(
            title='テスト曲', created_by=self.user,
            is_public=True, generation_status='completed',
        )
    
    def test_home_page_loads(self):
        """ホームページが読み込めること"""
        response = self.client.get(reverse('songs:home'))
        self.assertEqual(response.status_code, 200)
    
    def test_song_list_loads(self):
        """曲一覧ページが読み込めること"""
        response = self.client.get(reverse('songs:song_list'))
        self.assertEqual(response.status_code, 200)
    
    def test_song_detail_loads(self):
        """曲詳細ページが読み込めること"""
        response = self.client.get(reverse('songs:song_detail', args=[self.song.pk]))
        self.assertEqual(response.status_code, 200)
    
    def test_my_songs_requires_login(self):
        """マイ曲ページがログインを要求すること"""
        response = self.client.get(reverse('songs:my_songs'))
        self.assertEqual(response.status_code, 302)
    
    def test_my_songs_loads_when_logged_in(self):
        """ログイン時にマイ曲ページが読み込めること"""
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get(reverse('songs:my_songs'))
        self.assertEqual(response.status_code, 200)
    
    def test_delete_song_requires_login(self):
        """曲削除がログインを要求すること"""
        response = self.client.post(reverse('songs:delete_song', args=[self.song.pk]))
        self.assertEqual(response.status_code, 302)
    
    def test_delete_song_by_owner(self):
        """作成者が曲を削除できること"""
        self.client.login(username='testuser', password='testpass123')
        response = self.client.post(reverse('songs:delete_song', args=[self.song.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Song.objects.filter(pk=self.song.pk).exists())
    
    def test_delete_song_by_non_owner(self):
        """非作成者が曲を削除できないこと"""
        other_user = User.objects.create_user(username='other', password='testpass123')
        self.client.login(username='other', password='testpass123')
        response = self.client.post(reverse('songs:delete_song', args=[self.song.pk]))
        self.assertTrue(Song.objects.filter(pk=self.song.pk).exists())


class ContentFilterTest(TestCase):
    """コンテンツフィルターのテスト"""
    
    def test_clean_text_passes(self):
        """通常のテキストがフィルターを通過すること"""
        result = check_text_for_inappropriate_content('これは普通のテキストです')
        self.assertFalse(result['is_inappropriate'])
    
    def test_prohibited_word_blocked(self):
        """禁止ワードがブロックされること"""
        result = check_text_for_inappropriate_content('殺してやる')
        self.assertTrue(result['is_inappropriate'])
    
    def test_empty_text_passes(self):
        """空テキストがフィルターを通過すること"""
        result = check_text_for_inappropriate_content('')
        self.assertFalse(result['is_inappropriate'])
    
    def test_none_text_passes(self):
        """Noneがフィルターを通過すること"""
        result = check_text_for_inappropriate_content(None)
        self.assertFalse(result['is_inappropriate'])
    
    def test_result_has_expected_keys(self):
        """チェック結果に必要なキーが含まれていること"""
        result = check_text_for_inappropriate_content('テスト')
        self.assertIn('is_inappropriate', result)
        self.assertIn('detected_words', result)
    
    def test_academic_context_allowed(self):
        """学術的文脈の暴力系ワードが許可されること"""
        result = check_text_for_inappropriate_content('戦国時代の戦いについて学ぶ')
        self.assertFalse(result['is_inappropriate'])


class SetLanguageTest(TestCase):
    """言語切り替えのテスト"""
    
    def setUp(self):
        self.client = Client()
    
    def test_set_language_ja(self):
        """日本語に設定できること"""
        response = self.client.get(reverse('songs:set_language', args=['ja']))
        self.assertEqual(response.status_code, 302)
        session = self.client.session
        self.assertEqual(session.get('app_language'), 'ja')
    
    def test_set_language_en(self):
        """英語に設定できること"""
        response = self.client.get(reverse('songs:set_language', args=['en']))
        self.assertEqual(response.status_code, 302)
        session = self.client.session
        self.assertEqual(session.get('app_language'), 'en')
    
    def test_set_language_zh(self):
        """中国語に設定できること"""
        response = self.client.get(reverse('songs:set_language', args=['zh']))
        self.assertEqual(response.status_code, 302)
        session = self.client.session
        self.assertEqual(session.get('app_language'), 'zh')
    
    def test_set_language_es(self):
        """スペイン語に設定できること"""
        response = self.client.get(reverse('songs:set_language', args=['es']))
        self.assertEqual(response.status_code, 302)
        session = self.client.session
        self.assertEqual(session.get('app_language'), 'es')
    
    def test_set_invalid_language(self):
        """無効な言語コードが設定されないこと"""
        response = self.client.get(reverse('songs:set_language', args=['xx']))
        self.assertEqual(response.status_code, 302)
        session = self.client.session
        self.assertIsNone(session.get('app_language'))


class RecordPlayTest(TestCase):
    """再生記録のテスト"""
    
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='testuser', password='testpass123')
        self.song = Song.objects.create(
            title='テスト曲', created_by=self.user,
            is_public=True, generation_status='completed',
        )
    
    def test_record_play_increments_count(self):
        """再生記録で再生回数がインクリメントされること"""
        self.client.login(username='testuser', password='testpass123')
        initial_plays = self.song.total_plays
        response = self.client.post(reverse('songs:record_play', args=[self.song.pk]))
        self.assertEqual(response.status_code, 200)
        self.song.refresh_from_db()
        self.assertEqual(self.song.total_plays, initial_plays + 1)


class AudioProxyDomainTest(TestCase):
    """audio_proxyのドメインホワイトリストテスト"""
    
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='testuser', password='testpass123')
    
    def test_proxy_blocks_unauthorized_domain(self):
        """許可されていないドメインがブロックされること"""
        song = Song.objects.create(
            title='テスト曲', created_by=self.user,
            audio_url='https://evil.example.com/audio.mp3',
            generation_status='completed',
        )
        response = self.client.get(reverse('songs:audio_proxy', args=[song.pk]))
        self.assertEqual(response.status_code, 403)
    
    def test_proxy_returns_404_for_no_url(self):
        """audio_urlが空の場合404を返すこと"""
        song = Song.objects.create(
            title='テスト曲', created_by=self.user,
            audio_url='', generation_status='completed',
        )
        response = self.client.get(reverse('songs:audio_proxy', args=[song.pk]))
        self.assertEqual(response.status_code, 404)

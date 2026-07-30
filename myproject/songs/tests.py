import json
from io import StringIO

from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.db import IntegrityError
from django.core.management import call_command
from django.core.management.base import CommandError
from .models import (
    Song, Lyrics, Tag, Like, Favorite, Classroom, ClassroomMembership, ClassroomAssignment,
    FlashcardDeck, Flashcard, TheaterReservation,
    TrainingData, TrainingSession, DataPartner, DataPartnerAuthorization, PartnerDataAccessLog,
)
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
    
    def test_song_list_redirects_to_home(self):
        """曲一覧ページがホームにリダイレクトすること（公開一覧無効化）"""
        response = self.client.get(reverse('songs:song_list'))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('songs:home'))
    
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

    def test_university_content_with_smap_passes(self):
        """大学文脈でのSMAP表記が誤検知されないこと"""
        result = check_text_for_inappropriate_content('大学の授業でSMAPモデルについて学習する')
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

    def test_set_language_de(self):
        """ドイツ語に設定できること"""
        response = self.client.get(reverse('songs:set_language', args=['de']))
        self.assertEqual(response.status_code, 302)
        session = self.client.session
        self.assertEqual(session.get('app_language'), 'de')

    def test_set_language_pt(self):
        """ポルトガル語に設定できること"""
        response = self.client.get(reverse('songs:set_language', args=['pt']))
        self.assertEqual(response.status_code, 302)
        session = self.client.session
        self.assertEqual(session.get('app_language'), 'pt')

    def test_set_language_nl(self):
        """オランダ語に設定できること"""
        response = self.client.get(reverse('songs:set_language', args=['nl']))
        self.assertEqual(response.status_code, 302)
        session = self.client.session
        self.assertEqual(session.get('app_language'), 'nl')
    
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
            is_public=True,
        )
        response = self.client.get(reverse('songs:audio_proxy', args=[song.pk]))
        self.assertEqual(response.status_code, 403)
    
    def test_proxy_returns_404_for_no_url(self):
        """audio_urlが空の場合404を返すこと"""
        song = Song.objects.create(
            title='テスト曲', created_by=self.user,
            audio_url='', generation_status='completed',
            is_public=True,
        )
        response = self.client.get(reverse('songs:audio_proxy', args=[song.pk]))
        self.assertEqual(response.status_code, 404)


class ClassroomTest(TestCase):
    """クラス機能のテスト"""

    def setUp(self):
        self.client = Client()
        self.teacher = User.objects.create_user(username='teacher', password='testpass123')
        self.student = User.objects.create_user(username='student', password='testpass123')
        self.teacher.plan = 'school'
        self.teacher.save(update_fields=['plan'])
        self.student.plan = 'school'
        self.student.save(update_fields=['plan'])
        self.teacher.plan = 'school'
        self.teacher.save(update_fields=['plan'])
        self.student.plan = 'school'
        self.student.save(update_fields=['plan'])
        # スクールプラン設定（クラス機能はスクールプラン限定）
        self.teacher.plan = 'school'
        self.teacher.save()
        self.student.plan = 'school'
        self.student.save()

    def test_classroom_creation(self):
        """クラスが正しく作成されること"""
        classroom = Classroom.objects.create(
            name='テストクラス', code='ABC123', host=self.teacher
        )
        self.assertEqual(classroom.name, 'テストクラス')
        self.assertEqual(classroom.host, self.teacher)

    def test_classroom_code_unique(self):
        """クラスコードがユニークであること"""
        Classroom.objects.create(name='クラスA', code='UNQ001', host=self.teacher)
        with self.assertRaises(IntegrityError):
            Classroom.objects.create(name='クラスB', code='UNQ001', host=self.teacher)

    def test_classroom_membership(self):
        """生徒がクラスに参加できること"""
        classroom = Classroom.objects.create(
            name='テストクラス', code='JON001', host=self.teacher
        )
        membership = ClassroomMembership.objects.create(
            user=self.student, classroom=classroom
        )
        self.assertEqual(classroom.members.count(), 1)
        self.assertEqual(classroom.members.first(), self.student)

    def test_classroom_list_requires_login(self):
        """クラス一覧がログインを要求すること"""
        response = self.client.get(reverse('songs:classroom_list'))
        self.assertEqual(response.status_code, 302)


class TheaterBackendTest(TestCase):
    """UNITE CINEMA MINATO関連バックエンドのテスト"""

    def setUp(self):
        self.client = Client()

    def test_now_showing_page_loads(self):
        response = self.client.get(reverse('songs:unite_cinema_minato_now_showing'))
        self.assertEqual(response.status_code, 200)

    def test_coming_soon_page_loads(self):
        response = self.client.get(reverse('songs:unite_cinema_minato_coming_soon'))
        self.assertEqual(response.status_code, 200)

    def test_advance_tickets_page_loads(self):
        response = self.client.get(reverse('songs:unite_cinema_minato_advance_tickets'))
        self.assertEqual(response.status_code, 200)

    def test_schedule_api_returns_movies(self):
        response = self.client.get(reverse('songs:unite_cinema_minato_schedule_api'), {'date': '2026-06-05'})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn('movies', payload)
        self.assertTrue(len(payload['movies']) > 0)

    def test_reservation_api_returns_seat_status(self):
        date_query = '2026-06-05'
        schedule = self.client.get(reverse('songs:unite_cinema_minato_schedule_api'), {'date': date_query}).json()
        first_show = schedule['movies'][0]['shows'][0]
        show_key = first_show['show_key']
        TheaterReservation.objects.create(
            show_key=show_key,
            show_title=schedule['movies'][0]['title'],
            show_time=first_show['time'],
            seat_id='B1',
            guest_name='テスト',
        )

        response = self.client.get(
            reverse('songs:unite_cinema_minato_reservation_api'),
            {'date': date_query, 'show': show_key},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['success'])
        self.assertIn('B1', payload['reserved_seat_ids'])

    def test_reservation_api_returns_400_for_invalid_show(self):
        response = self.client.get(
            reverse('songs:unite_cinema_minato_reservation_api'),
            {'date': '2026-06-05', 'show': 'invalid-show-key'},
        )
        self.assertEqual(response.status_code, 400)


class ClassroomTest(TestCase):
    """クラス機能のテスト"""

    def setUp(self):
        self.client = Client()
        self.teacher = User.objects.create_user(username='teacher', password='testpass123')
        self.student = User.objects.create_user(username='student', password='testpass123')
        self.teacher.plan = 'school'
        self.teacher.save(update_fields=['plan'])
        self.student.plan = 'school'
        self.student.save(update_fields=['plan'])

    def test_classroom_list_loads(self):
        """ログイン時にクラス一覧が読み込めること"""
        self.client.login(username='teacher', password='testpass123')
        response = self.client.get(reverse('songs:classroom_list'))
        # 無効コードの場合、テンプレートでエラー表示（200）
        self.assertIn(response.status_code, [200, 302])

    def test_classroom_join_with_valid_code(self):
        """有効なコードでクラスに参加できること"""
        classroom = Classroom.objects.create(
            name='テストクラス', code='VAL001', host=self.teacher
        )
        self.client.login(username='student', password='testpass123')
        response = self.client.post(reverse('songs:classroom_join'), {'code': 'VAL001'})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(ClassroomMembership.objects.filter(
            user=self.student, classroom=classroom
        ).exists())

    def test_classroom_join_with_invalid_code(self):
        """無効なコードでクラスに参加できないこと"""
        self.client.login(username='student', password='testpass123')
        response = self.client.post(reverse('songs:classroom_join'), {'code': 'INVALID'})
        # 無効コードの場合、エラー表示で再レンダリング（200）
        self.assertIn(response.status_code, [200, 302])
        self.assertEqual(ClassroomMembership.objects.filter(user=self.student).count(), 0)

    def test_classroom_leave(self):
        """クラスから退出できること"""
        classroom = Classroom.objects.create(
            name='テストクラス', code='LEV001', host=self.teacher
        )
        ClassroomMembership.objects.create(user=self.student, classroom=classroom)
        self.client.login(username='student', password='testpass123')
        response = self.client.post(reverse('songs:classroom_leave', args=[classroom.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(ClassroomMembership.objects.filter(
            user=self.student, classroom=classroom
        ).exists())

    def test_host_can_delete_classroom(self):
        """ホストがクラスを削除できること"""
        classroom = Classroom.objects.create(
            name='テストクラス', code='DEL001', host=self.teacher
        )
        self.client.login(username='teacher', password='testpass123')
        response = self.client.post(reverse('songs:classroom_delete', args=[classroom.pk]))
        self.assertEqual(response.status_code, 302)
        # ソフトデリート: is_active=False になる（物理削除ではない）
        classroom.refresh_from_db()
        self.assertFalse(classroom.is_active)

    def test_non_host_cannot_delete_classroom(self):
        """非ホストがクラスを削除できないこと"""
        classroom = Classroom.objects.create(
            name='テストクラス', code='NDL001', host=self.teacher
        )
        ClassroomMembership.objects.create(user=self.student, classroom=classroom)
        self.client.login(username='student', password='testpass123')
        response = self.client.post(reverse('songs:classroom_delete', args=[classroom.pk]))
        classroom.refresh_from_db()
        self.assertTrue(classroom.is_active)

    def test_teacher_permission_can_open_classroom_create(self):
        """先生権限ユーザーはクラス作成ページにアクセスできること"""
        self.teacher.is_teacher = True
        self.teacher.save(update_fields=['is_teacher'])
        self.client.login(username='teacher', password='testpass123')
        response = self.client.get(reverse('songs:classroom_create'))
        self.assertEqual(response.status_code, 200)

    def test_classroom_assignment_model_creation(self):
        """クラス課題モデルが作成できること"""
        classroom = Classroom.objects.create(
            name='テストクラス', code='ASG001', host=self.teacher
        )
        song = Song.objects.create(
            title='課題曲',
            created_by=self.teacher,
            generation_status='completed',
        )
        assignment = ClassroomAssignment.objects.create(
            classroom=classroom,
            song=song,
            assigned_by=self.teacher,
            note='1番を覚える',
        )
        self.assertEqual(assignment.classroom, classroom)
        self.assertEqual(assignment.song, song)


class FlashcardTest(TestCase):
    """フラッシュカード機能のテスト"""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='testuser', password='testpass123')
        self.song = Song.objects.create(
            title='テスト曲', created_by=self.user, generation_status='completed'
        )

    def test_flashcard_deck_creation(self):
        """デッキが正しく作成されること"""
        deck = FlashcardDeck.objects.create(
            user=self.user, title='テストデッキ', source_song=self.song
        )
        self.assertEqual(deck.title, 'テストデッキ')
        self.assertEqual(deck.card_count, 0)

    def test_flashcard_creation(self):
        """カードが正しく作成されること"""
        deck = FlashcardDeck.objects.create(user=self.user, title='テストデッキ')
        card = Flashcard.objects.create(
            deck=deck, term='織田信長', definition='戦国時代の武将'
        )
        self.assertEqual(card.term, '織田信長')
        self.assertEqual(card.mastery_level, 0)

    def test_flashcard_mastery_update(self):
        """カードの習熟度が更新できること"""
        deck = FlashcardDeck.objects.create(user=self.user, title='テストデッキ')
        card = Flashcard.objects.create(
            deck=deck, term='本能寺の変', definition='1582年', is_selected=True
        )
        card.mastery_level = 3
        card.save()
        card.refresh_from_db()
        self.assertEqual(card.mastery_level, 3)

    def test_deck_card_count_update(self):
        """デッキのカード数が正しく更新されること"""
        deck = FlashcardDeck.objects.create(user=self.user, title='テストデッキ')
        Flashcard.objects.create(deck=deck, term='用語1', definition='定義1', is_selected=True)
        Flashcard.objects.create(deck=deck, term='用語2', definition='定義2', is_selected=True)
        Flashcard.objects.create(deck=deck, term='用語3', definition='定義3', is_selected=False)
        deck.update_card_count()
        self.assertEqual(deck.card_count, 2)

    def test_flashcard_list_requires_login(self):
        """フラッシュカード一覧がログインを要求すること"""
        response = self.client.get(reverse('songs:flashcard_list'))
        self.assertEqual(response.status_code, 302)

    def test_flashcard_list_loads(self):
        """ログイン時にフラッシュカード一覧が読み込めること"""
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get(reverse('songs:flashcard_list'))
        self.assertEqual(response.status_code, 200)

    def test_flashcard_study_loads(self):
        """学習ページが読み込めること"""
        deck = FlashcardDeck.objects.create(user=self.user, title='テストデッキ')
        Flashcard.objects.create(deck=deck, term='用語', definition='定義', is_selected=True)
        deck.update_card_count()
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get(reverse('songs:flashcard_study', args=[deck.pk]))
        self.assertEqual(response.status_code, 200)

    def test_flashcard_deck_delete(self):
        """デッキが削除できること"""
        deck = FlashcardDeck.objects.create(user=self.user, title='テストデッキ')
        self.client.login(username='testuser', password='testpass123')
        response = self.client.post(reverse('songs:flashcard_deck_delete', args=[deck.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(FlashcardDeck.objects.filter(pk=deck.pk).exists())

    def test_other_user_cannot_delete_deck(self):
        """他ユーザーのデッキを削除できないこと"""
        deck = FlashcardDeck.objects.create(user=self.user, title='テストデッキ')
        other = User.objects.create_user(username='other', password='testpass123')
        self.client.login(username='other', password='testpass123')
        response = self.client.post(reverse('songs:flashcard_deck_delete', args=[deck.pk]))
        self.assertTrue(FlashcardDeck.objects.filter(pk=deck.pk).exists())


class DataPartnerVisibilityTest(TestCase):
    """TrainingData.objects.visible_to() のアクセス制御テスト（データ提供元の覚書 第3条対応）"""

    def setUp(self):
        self.superuser = User.objects.create_superuser(username='super', password='testpass123')
        self.staff_authorized = User.objects.create_user(username='staff_ok', password='testpass123', is_staff=True)
        self.staff_other = User.objects.create_user(username='staff_no', password='testpass123', is_staff=True)
        self.partner = DataPartner.objects.create(slug='clearnote', name='Clearnote')
        DataPartnerAuthorization.objects.create(data_partner=self.partner, user=self.staff_authorized)
        self.organic = TrainingData.objects.create(instruction='i', input_text='organic input', output_text='o')
        self.partner_row = TrainingData.objects.create(
            instruction='i', input_text='partner input', output_text='o', data_partner=self.partner,
        )

    def test_superuser_sees_all(self):
        visible = TrainingData.objects.visible_to(self.superuser)
        self.assertIn(self.organic, visible)
        self.assertIn(self.partner_row, visible)

    def test_unauthorized_staff_excludes_partner_data(self):
        visible = TrainingData.objects.visible_to(self.staff_other)
        self.assertIn(self.organic, visible)
        self.assertNotIn(self.partner_row, visible)

    def test_authorized_staff_sees_partner_data(self):
        visible = TrainingData.objects.visible_to(self.staff_authorized)
        self.assertIn(self.organic, visible)
        self.assertIn(self.partner_row, visible)

    def test_none_user_sees_only_organic(self):
        visible = TrainingData.objects.visible_to(None)
        self.assertIn(self.organic, visible)
        self.assertNotIn(self.partner_row, visible)


class TrainingDataDownloadApiTest(TestCase):
    """training_data_download API のパートナーデータ・ゲーティングと監査ログのテスト"""

    def setUp(self):
        self.operator = User.objects.create_user(username='operator', password='testpass123', is_staff=True)
        self.partner = DataPartner.objects.create(slug='clearnote', name='Clearnote')
        DataPartnerAuthorization.objects.create(data_partner=self.partner, user=self.operator)
        TrainingData.objects.create(instruction='i', input_text='organic', output_text='o')
        TrainingData.objects.create(
            instruction='i', input_text='partner data', output_text='o', data_partner=self.partner,
        )

    def test_missing_api_key(self):
        response = self.client.get(reverse('songs:training_data_download'))
        self.assertEqual(response.status_code, 401)

    def test_invalid_api_key(self):
        response = self.client.get(
            reverse('songs:training_data_download'), HTTP_X_TRAINING_API_KEY='bogus-key',
        )
        self.assertEqual(response.status_code, 403)

    def test_session_without_operator_excludes_partner_data(self):
        """operated_by未設定のセッションはパートナーデータを取得できない（フェイルクローズ）"""
        session = TrainingSession.objects.create(machine_name='home-pc')
        response = self.client.get(
            reverse('songs:training_data_download'), HTTP_X_TRAINING_API_KEY=session.api_key,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['total'], 1)
        self.assertEqual(PartnerDataAccessLog.objects.filter(action='download').count(), 0)

    def test_session_with_authorized_operator_includes_partner_data_and_logs(self):
        session = TrainingSession.objects.create(machine_name='school-pc', operated_by=self.operator)
        response = self.client.get(
            reverse('songs:training_data_download'), HTTP_X_TRAINING_API_KEY=session.api_key,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['total'], 2)
        log = PartnerDataAccessLog.objects.get(action='download')
        self.assertEqual(log.data_partner, self.partner)
        self.assertEqual(log.record_count, 1)
        self.assertEqual(log.training_session, session)


class TrainingDataUploadReplaceGuardTest(TestCase):
    """training_data_upload の mode=replace がパートナーデータを保持し、hash衝突でも500にならないことのテスト"""

    def setUp(self):
        self.session = TrainingSession.objects.create(machine_name='home-pc')
        self.partner = DataPartner.objects.create(slug='clearnote', name='Clearnote')
        self.partner_row = TrainingData.objects.create(
            instruction='i', input_text='partner input text', output_text='partner output',
            data_partner=self.partner,
        )
        self.organic_row = TrainingData.objects.create(
            instruction='i', input_text='organic input text', output_text='organic output',
        )

    def test_replace_preserves_partner_rows(self):
        response = self.client.post(
            reverse('songs:training_data_upload'),
            data=json.dumps({
                'mode': 'replace',
                'records': [{'instruction': 'new', 'input': 'brand new organic text', 'output': 'new output'}],
            }),
            content_type='application/json',
            HTTP_X_TRAINING_API_KEY=self.session.api_key,
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(TrainingData.objects.filter(pk=self.organic_row.pk).exists())
        self.assertTrue(TrainingData.objects.filter(pk=self.partner_row.pk).exists())
        self.assertTrue(TrainingData.objects.filter(input_text='brand new organic text').exists())

    def test_replace_skips_hash_collision_with_partner_row_without_error(self):
        response = self.client.post(
            reverse('songs:training_data_upload'),
            data=json.dumps({
                'mode': 'replace',
                'records': [{'instruction': 'i', 'input': 'partner input text', 'output': 'different output'}],
            }),
            content_type='application/json',
            HTTP_X_TRAINING_API_KEY=self.session.api_key,
        )
        self.assertEqual(response.status_code, 200)
        self.partner_row.refresh_from_db()
        self.assertEqual(self.partner_row.output_text, 'partner output')
        self.assertEqual(TrainingData.objects.filter(input_text='partner input text').count(), 1)


class PurgePartnerDataCommandTest(TestCase):
    """purge_partner_data management command のテスト（データ提供元の覚書 第4条対応）"""

    def setUp(self):
        self.partner = DataPartner.objects.create(slug='testpartner', name='Test Partner')
        self.row = TrainingData.objects.create(
            instruction='i', input_text='unique purge test input xyz123', output_text='o',
            data_partner=self.partner,
        )

    def test_dry_run_makes_no_changes(self):
        out = StringIO()
        call_command('purge_partner_data', 'testpartner', stdout=out)
        self.assertTrue(TrainingData.objects.filter(pk=self.row.pk).exists())
        self.partner.refresh_from_db()
        self.assertTrue(self.partner.is_active)
        self.assertEqual(PartnerDataAccessLog.objects.count(), 0)

    def test_yes_purges_and_logs(self):
        out = StringIO()
        call_command('purge_partner_data', 'testpartner', '--yes', '--reason', 'test', stdout=out)
        self.assertFalse(TrainingData.objects.filter(pk=self.row.pk).exists())
        self.partner.refresh_from_db()
        self.assertFalse(self.partner.is_active)
        log = PartnerDataAccessLog.objects.get(action='delete')
        self.assertEqual(log.data_partner, self.partner)
        self.assertEqual(log.record_count, 1)

    def test_unknown_partner_raises(self):
        with self.assertRaises(CommandError):
            call_command('purge_partner_data', 'doesnotexist')

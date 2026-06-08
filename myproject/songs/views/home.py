"""ホーム・一覧・詳細系ビュー"""
from django.shortcuts import get_object_or_404, redirect
from django.http import JsonResponse
from django.views.generic import ListView, DetailView, TemplateView
from django.db import IntegrityError, transaction
from django.db.models import Q, Count, F, Case, When, IntegerField, Value
from django.conf import settings
from django.core.mail import send_mail
from django.views.decorators.http import require_http_methods
from datetime import date, datetime, timedelta
import random
import logging

from ..models import Song, Like, Favorite, Comment, PlayHistory, FlashcardDeck, TheaterReservation, TheaterSurveyResponse
from ..forms import CommentForm

logger = logging.getLogger(__name__)


THEATER_BASE_DATE = date(2026, 6, 5)
THEATER_WEEKDAYS = ('月', '火', '水', '木', '金', '土', '日')
THEATER_MOVIES = (
    {'slug': 'kiminonawa', 'title': '君の名は。 / G', 'minutes': 107, 'screen': '1'},
    {'slug': 'tenkinoko', 'title': '天気の子 / G', 'minutes': 112, 'screen': '1'},
    {'slug': 'oppenheimer', 'title': 'Oppenheimer／オッペンハイマー / R15+', 'minutes': 180, 'screen': '1'},
    {'slug': 'topgun', 'title': 'Top Gun: Maverick／トップガン マーヴェリック / G', 'minutes': 130, 'screen': '1'},
    {'slug': 'hathaway', 'title': '機動戦士ガンダム 閃光のハサウェイ / G', 'minutes': 95, 'screen': '1'},
    {'slug': 'ado-live', 'title': '劇場版 Ado SPECIAL LIVE「心臓」 / G', 'minutes': 139, 'screen': '1'},
    {'slug': 'kaguyahime', 'title': '超かぐや姫！ / G', 'minutes': 98, 'screen': '1'},
    {'slug': 'godzilla', 'title': 'ゴジラ-1.0 / G', 'minutes': 125, 'screen': '1'},
    {'slug': 'mononoke-4k', 'title': 'もののけ姫 4Kリマスター / G', 'minutes': 134, 'screen': '1'},
)
THEATER_TIME_SLOTS = ('09:00', '10:10', '11:25', '12:45', '14:05', '15:30', '16:55', '18:20', '19:45', '21:10', '22:20')

THEATER_SEAT_ROWS = (
    {
        'label': '一番前 寝そべりシート',
        'class': 'front-row',
        'seats': (
            {'id': 'A1', 'label': '寝A1', 'type': 'lie'},
            {'id': 'A2', 'label': '寝A2', 'type': 'lie'},
            {'id': 'A3', 'label': '寝A3', 'type': 'lie'},
        ),
    },
    {
        'label': '真ん中シート',
        'class': 'middle-row',
        'seats': (
            {'id': 'B1', 'label': 'B1', 'type': 'standard'},
            {'id': 'B2', 'label': 'B2', 'type': 'standard'},
            {'id': 'B3', 'label': 'B3', 'type': 'standard'},
            {'id': 'B4', 'label': 'B4', 'type': 'standard'},
        ),
    },
    {
        'label': '後ろシート',
        'class': 'back-row',
        'seats': (
            {'id': 'C1', 'label': 'C1', 'type': 'standard'},
            {'id': 'C2', 'label': 'C2', 'type': 'standard'},
            {'id': 'C3', 'label': 'C3', 'type': 'standard'},
        ),
    },
)


def _parse_theater_date(value):
    try:
        return datetime.strptime(value or '', '%Y-%m-%d').date()
    except ValueError:
        return THEATER_BASE_DATE


def _format_theater_date(value):
    return f"{value.month}/{value.day}({THEATER_WEEKDAYS[value.weekday()]})"


def _add_minutes(time_text, minutes):
    start = datetime.strptime(time_text, '%H:%M')
    return (start + timedelta(minutes=minutes)).strftime('%H:%M')


def _build_theater_schedule(selected_date):
    rng = random.Random(f"unite-cinema-minato:{selected_date.isoformat()}")
    movies = [dict(movie) for movie in THEATER_MOVIES]
    rng.shuffle(movies)

    extra_count = 1 + (selected_date.toordinal() % 3)
    extra_movies = set()
    for offset in range(extra_count):
        extra_movies.add(movies[(selected_date.toordinal() + offset) % len(movies)]['slug'])

    show_items = []
    slot_index = 0
    for movie in movies:
        show_count = 2 if movie['slug'] in extra_movies else 1
        for _ in range(show_count):
            if slot_index >= len(THEATER_TIME_SLOTS):
                break
            start_time = THEATER_TIME_SLOTS[slot_index]
            show_items.append({
                **movie,
                'time': start_time,
                'end_time': _add_minutes(start_time, movie['minutes']),
                'show_key': f"{movie['slug']}-{selected_date.strftime('%Y%m%d')}-{start_time.replace(':', '')}",
            })
            slot_index += 1

    grouped = []
    for movie in movies:
        shows = [show for show in show_items if show['slug'] == movie['slug']]
        if shows:
            grouped.append({**movie, 'shows': shows, 'blank_cells': range(7 - len(shows))})
    return grouped


def _flatten_theater_schedule(selected_date):
    return {
        show['show_key']: show
        for movie in _build_theater_schedule(selected_date)
        for show in movie['shows']
    }


def _serialize_theater_schedule_for_api(schedule_movies):
    serialized = []
    for movie in schedule_movies:
        serialized.append({
            'slug': movie['slug'],
            'title': movie['title'],
            'minutes': movie['minutes'],
            'screen': movie['screen'],
            'shows': [
                {
                    'time': show['time'],
                    'end_time': show['end_time'],
                    'show_key': show['show_key'],
                    'slug': show['slug'],
                }
                for show in movie['shows']
            ],
        })
    return serialized


def _validate_theater_survey_input(survey_name, survey_show, survey_memo):
    errors = []

    if not survey_show:
        errors.append('日曜日の上映会で見たい作品を入力してください。')
    elif len(survey_show) > 120:
        errors.append('見たい作品は120文字以内で入力してください。')

    if len(survey_name) > 80:
        errors.append('お名前は80文字以内で入力してください。')

    if len(survey_memo) > 300:
        errors.append('ひとことは300文字以内で入力してください。')

    return errors


class HomeView(TemplateView):
    """ホームページビュー"""
    template_name = 'songs/home.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # 公開楽曲一覧は著作権保護のため無効化
        context['recent_songs'] = []
        context['popular_songs'] = []
        return context


class TheaterArchiveView(TemplateView):
    """映画館風の独立アーカイブページ"""
    template_name = 'songs/theater_archive.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        selected_date = _parse_theater_date(self.request.GET.get('date'))
        week_start = THEATER_BASE_DATE
        date_tabs = []
        for offset in range(7):
            day = week_start + timedelta(days=offset)
            date_tabs.append({
                'date': day,
                'query': day.isoformat(),
                'month': f'{day.month}/',
                'day': day.day,
                'week': THEATER_WEEKDAYS[day.weekday()],
                'week_class': 'blue' if day.weekday() == 5 else 'red' if day.weekday() == 6 else '',
                'active': day == selected_date,
            })
        context['selected_date'] = selected_date
        context['selected_date_query'] = selected_date.isoformat()
        context['selected_date_label'] = _format_theater_date(selected_date)
        context['prev_date_query'] = (selected_date - timedelta(days=1)).isoformat()
        context['next_date_query'] = (selected_date + timedelta(days=1)).isoformat()
        context['date_tabs'] = date_tabs
        context['schedule_movies'] = _build_theater_schedule(selected_date)
        return context


class TheaterNowShowingView(TemplateView):
    """上映中作品ページ"""
    template_name = 'songs/theater_now_showing.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        selected_date = _parse_theater_date(self.request.GET.get('date'))
        schedule = _build_theater_schedule(selected_date)
        context['selected_date'] = selected_date
        context['selected_date_query'] = selected_date.isoformat()
        context['selected_date_label'] = _format_theater_date(selected_date)
        context['now_showing_movies'] = schedule
        return context


class TheaterComingSoonView(TemplateView):
    """公開予定作品ページ"""
    template_name = 'songs/theater_coming_soon.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        selected_date = _parse_theater_date(self.request.GET.get('date'))
        upcoming_movies = []
        for index, movie in enumerate(THEATER_MOVIES):
            release_date = selected_date + timedelta(days=(index + 1) * 7)
            upcoming_movies.append({
                'title': movie['title'],
                'release_date': release_date,
                'release_date_label': _format_theater_date(release_date),
                'minutes': movie['minutes'],
            })
        context['upcoming_movies'] = upcoming_movies[:8]
        return context


class TheaterAdvanceTicketsView(TemplateView):
    """前売情報ページ"""
    template_name = 'songs/theater_advance_tickets.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        selected_date = _parse_theater_date(self.request.GET.get('date'))
        ticket_items = []
        for index, movie in enumerate(THEATER_MOVIES[:6]):
            release_date = selected_date + timedelta(days=(index + 1) * 7)
            sales_end = release_date - timedelta(days=1)
            ticket_items.append({
                'title': movie['title'],
                'price': 1400 + (index % 3) * 200,
                'sales_end_label': _format_theater_date(sales_end),
                'release_date_label': _format_theater_date(release_date),
            })
        context['ticket_items'] = ticket_items
        return context


@require_http_methods(['GET'])
def theater_schedule_api(request):
    """上映スケジュールJSON API"""
    selected_date = _parse_theater_date(request.GET.get('date'))
    schedule = _build_theater_schedule(selected_date)
    return JsonResponse({
        'date': selected_date.isoformat(),
        'date_label': _format_theater_date(selected_date),
        'movies': _serialize_theater_schedule_for_api(schedule),
    })


@require_http_methods(['GET'])
def theater_reservation_status_api(request):
    """指定上映回の予約状況JSON API"""
    selected_date = _parse_theater_date(request.GET.get('date'))
    schedule = _flatten_theater_schedule(selected_date)
    show_key = request.GET.get('show', '').strip()
    show = schedule.get(show_key)

    if not show:
        return JsonResponse({'success': False, 'error': 'show が不正です。'}, status=400)

    reserved_seat_ids = list(
        TheaterReservation.objects.filter(show_key=show_key).values_list('seat_id', flat=True)
    )
    total_seats = sum(len(row['seats']) for row in THEATER_SEAT_ROWS)

    return JsonResponse({
        'success': True,
        'date': selected_date.isoformat(),
        'show_key': show_key,
        'show_title': show['title'],
        'show_time': show['time'],
        'reserved_count': len(reserved_seat_ids),
        'total_seats': total_seats,
        'available_count': max(total_seats - len(reserved_seat_ids), 0),
        'reserved_seat_ids': reserved_seat_ids,
    })


class TheaterSurveyView(TemplateView):
    """映画館風ページのアンケート専用ページ"""
    template_name = 'songs/theater_survey.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['survey_name'] = kwargs.get('survey_name', '')
        context['survey_show'] = kwargs.get('survey_show', '')
        context['survey_memo'] = kwargs.get('survey_memo', '')
        context['survey_errors'] = kwargs.get('survey_errors', [])
        context['survey_success_message'] = kwargs.get('survey_success_message', '')
        return context

    def _notify_admin(self, survey_name, survey_show, survey_memo):
        admin_email = getattr(settings, 'ADMIN_NOTIFICATION_EMAIL', 'admin@utamemo.com')
        subject = '【UNITE CINEMA MINATO】アンケート回答が届きました'
        display_name = survey_name or '匿名'
        message = (
            f'お名前: {display_name}\n'
            f'見たい作品: {survey_show}\n'
            f'ひとこと: {survey_memo or "(未入力)"}\n'
        )
        try:
            send_mail(
                subject=subject,
                message=message,
                from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@utamemo.com'),
                recipient_list=[admin_email],
                fail_silently=True,
            )
        except Exception as exc:
            logger.warning('Survey admin notify failed: %s', exc)

    def post(self, request, *args, **kwargs):
        survey_name = request.POST.get('survey_name', '').strip()
        survey_show = request.POST.get('survey_show', '').strip()
        survey_memo = request.POST.get('survey_memo', '').strip()
        survey_errors = _validate_theater_survey_input(survey_name, survey_show, survey_memo)

        if survey_errors:
            context = self.get_context_data(
                survey_name=survey_name,
                survey_show=survey_show,
                survey_memo=survey_memo,
                survey_errors=survey_errors,
            )
            return self.render_to_response(context)

        TheaterSurveyResponse.objects.create(
            visitor_name=survey_name,
            desired_show=survey_show,
            memo=survey_memo,
        )

        self._notify_admin(survey_name, survey_show, survey_memo)

        context = self.get_context_data(
            survey_success_message='アンケートを受け付けました。',
        )
        return self.render_to_response(context)


class TheaterPriceView(TemplateView):
    """映画館風ページの料金ページ"""
    template_name = 'songs/theater_price.html'


class TheaterAccessView(TemplateView):
    """映画館風ページのアクセスページ"""
    template_name = 'songs/theater_access.html'


class TheaterGuideView(TemplateView):
    """映画館風ページの劇場案内ページ"""
    template_name = 'songs/theater_guide.html'


class TheaterReservationView(TemplateView):
    """アカウントなしで使える簡易座席予約ページ"""
    template_name = 'songs/theater_reservation.html'

    show_slug_aliases = {
        'mononoke': 'mononoke-4k',
    }

    def _get_selected_date(self):
        date_value = self.request.POST.get('date') or self.request.GET.get('date')
        if date_value:
            return _parse_theater_date(date_value)

        show_key = self.request.POST.get('show') or self.request.GET.get('show') or ''
        for part in show_key.split('-'):
            if len(part) == 8 and part.isdigit():
                try:
                    return datetime.strptime(part, '%Y%m%d').date()
                except ValueError:
                    break
        return THEATER_BASE_DATE

    def _get_requested_show_key(self):
        return self.request.POST.get('show') or self.request.GET.get('show') or ''

    def _resolve_show_key(self, schedule):
        requested_key = self._get_requested_show_key()
        fallback_key = next(iter(schedule))

        if requested_key in schedule:
            return requested_key

        for movie in THEATER_MOVIES:
            slug = movie['slug']
            legacy_slug = self.show_slug_aliases.get(requested_key.rsplit('-', 1)[0], requested_key.rsplit('-', 1)[0])
            if legacy_slug == slug or requested_key.startswith(f'{slug}-'):
                for show_key, show in schedule.items():
                    if show['slug'] == slug:
                        return show_key

        return fallback_key

    def _get_show_key(self):
        return self._resolve_show_key(_flatten_theater_schedule(self._get_selected_date()))

    def _get_show(self, show_key):
        schedule = _flatten_theater_schedule(self._get_selected_date())
        return schedule[self._resolve_show_key(schedule) if show_key not in schedule else show_key]

    def _build_seat_rows(self, show_key):
        reservations = {
            reservation.seat_id: reservation
            for reservation in TheaterReservation.objects.filter(show_key=show_key)
        }
        seat_rows = []
        for row in THEATER_SEAT_ROWS:
            seats = []
            for seat in row['seats']:
                reservation = reservations.get(seat['id'])
                seats.append({
                    **seat,
                    'reserved': reservation is not None,
                })
            seat_rows.append({**row, 'seats': seats})
        return seat_rows

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        selected_date = self._get_selected_date()
        show_key = self._get_show_key()
        show = self._get_show(show_key)
        reservations = TheaterReservation.objects.filter(show_key=show_key).count()
        context['show_key'] = show_key
        context['show'] = show
        context['show_date_query'] = selected_date.isoformat()
        context['show_date_label'] = _format_theater_date(selected_date)
        context['reserved_count'] = reservations
        context['total_seats'] = sum(len(row['seats']) for row in THEATER_SEAT_ROWS)
        context['seat_rows'] = self._build_seat_rows(show_key)
        context['selected_seat_id'] = kwargs.get('selected_seat_id', '')
        context['guest_name'] = kwargs.get('guest_name', '')
        context['errors'] = kwargs.get('errors', [])
        context['success_message'] = kwargs.get('success_message', '')
        return context

    def _notify_admin(self, show, show_key, seat_id, guest_name, selected_date):
        admin_email = getattr(settings, 'ADMIN_NOTIFICATION_EMAIL', 'admin@utamemo.com')
        subject = f'【UNITE CINEMA MINATO】予約が入りました: {show["title"]}'
        message = (
            f'作品: {show["title"]}\n'
            f'上映日: {_format_theater_date(selected_date)}\n'
            f'上映時間: {show["time"]}〜{show["end_time"]}\n'
            f'座席: {seat_id}\n'
            f'予約名: {guest_name}\n'
            f'予約キー: {show_key}\n'
        )
        try:
            send_mail(
                subject=subject,
                message=message,
                from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@utamemo.com'),
                recipient_list=[admin_email],
                fail_silently=True,
            )
        except Exception as exc:
            logger.warning('Reservation admin notify failed: %s', exc)

    def post(self, request, *args, **kwargs):
        selected_date = self._get_selected_date()
        show_key = self._get_show_key()
        show = self._get_show(show_key)
        seat_id = request.POST.get('seat_id', '').strip()
        guest_name = request.POST.get('guest_name', '').strip()
        valid_seat_ids = {
            seat['id']
            for row in THEATER_SEAT_ROWS
            for seat in row['seats']
        }
        errors = []

        if seat_id not in valid_seat_ids:
            errors.append('席を選んでください。')
        if not guest_name:
            errors.append('予約する名前を入力してください。')
        elif len(guest_name) > 80:
            errors.append('名前は80文字以内で入力してください。')

        if not errors:
            try:
                with transaction.atomic():
                    reservation, created = TheaterReservation.objects.get_or_create(
                        show_key=show_key,
                        seat_id=seat_id,
                        defaults={
                            'show_title': show['title'],
                            'show_time': show['time'],
                            'guest_name': guest_name,
                        },
                    )
                if not created:
                    errors.append('この席はすでに予約されています。別の席を選んでください。')
            except IntegrityError:
                errors.append('この席はすでに予約されています。別の席を選んでください。')

        if errors:
            context = self.get_context_data(
                selected_seat_id=seat_id,
                guest_name=guest_name,
                errors=errors,
            )
            return self.render_to_response(context)

        self._notify_admin(show, show_key, seat_id, guest_name, selected_date)

        context = self.get_context_data(
            success_message=f'{guest_name}さんの予約を受け付けました。席は{seat_id}です。',
        )
        return self.render_to_response(context)


class SongListView(ListView):
    """楽曲一覧ビュー（著作権保護のため公開一覧を無効化 — ホームにリダイレクト）"""
    model = Song
    template_name = 'songs/song_list.html'
    context_object_name = 'songs'
    paginate_by = 12

    def get(self, request, *args, **kwargs):
        return redirect('songs:home')


def song_share_redirect(request, share_id):
    """シェアURL（/s/<share_id>/）から曲詳細ページにリダイレクト"""
    song = get_object_or_404(Song, share_id=share_id)
    return redirect('songs:song_detail', pk=song.pk)


class SongDetailView(DetailView):
    """楽曲詳細ビュー"""
    model = Song
    template_name = 'songs/song_detail.html'
    context_object_name = 'song'
    
    def get_queryset(self):
        return Song.objects.select_related('created_by', 'lyrics').prefetch_related('tags')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        song = self.object
        
        # 歌詞情報の安全な取得
        try:
            if hasattr(song, 'lyrics') and song.lyrics:
                context['lyrics_content'] = song.lyrics.content or ''
                context['decrypted_lyrics'] = song.lyrics.content or ''
                context['original_text'] = song.lyrics.original_text or ''
                context['decrypted_original_text'] = song.lyrics.original_text or ''
            else:
                context['lyrics_content'] = ''
                context['original_text'] = ''
                context['decrypted_lyrics'] = ''
                context['decrypted_original_text'] = ''
        except Exception:
            context['lyrics_content'] = ''
            context['original_text'] = ''
            context['decrypted_lyrics'] = ''
            context['decrypted_original_text'] = ''
        
        # 認証ユーザーの情報
        if self.request.user.is_authenticated:
            context['is_liked'] = Like.objects.filter(
                user=self.request.user, song=song
            ).exists()
            context['is_favorited'] = Favorite.objects.filter(
                user=self.request.user, song=song
            ).exists()
            # ユーザーの再生回数を取得
            try:
                play_history = PlayHistory.objects.get(user=self.request.user, song=song)
                context['my_play_count'] = play_history.play_count
            except PlayHistory.DoesNotExist:
                context['my_play_count'] = 0
        else:
            context['is_liked'] = False
            context['is_favorited'] = False
            context['my_play_count'] = 0
            
        context['comments'] = Comment.objects.filter(song=song).select_related('user')
        context['comment_form'] = CommentForm()
        
        # 関連楽曲を取得（同じタグまたは似た名前の公開楽曲）
        try:
            context['related_songs'] = self._get_related_songs(song)
        except Exception:
            context['related_songs'] = []
        
        # この楽曲の暗記カードデッキ
        if self.request.user.is_authenticated and self.request.user == song.created_by:
            context['flashcard_deck'] = FlashcardDeck.objects.filter(
                source_song=song, user=self.request.user
            ).first()
        
        # シェア用URL
        context['share_url'] = self.request.build_absolute_uri(song.get_share_url())
        
        return context
    
    def _get_related_songs(self, song):
        """関連楽曲を取得 - ジャンル、タグ、作成者で関連性を計算"""
        # 自分自身を除外し、公開済みの楽曲のみ
        related = Song.objects.filter(
            is_public=True,
            generation_status='completed'
        ).exclude(pk=song.pk)
        
        # スコアリングで関連度を計算
        song_tags = song.tags.all()
        tag_ids = list(song_tags.values_list('id', flat=True)) if song_tags.exists() else []
        
        # 同じジャンルかどうか
        genre_match = Case(
            When(genre=song.genre, then=Value(10)) if song.genre else When(pk__isnull=True, then=Value(0)),
            default=Value(0),
            output_field=IntegerField()
        )
        
        # 同じ作成者かどうか
        creator_match = Case(
            When(created_by=song.created_by, then=Value(5)),
            default=Value(0),
            output_field=IntegerField()
        )
        
        # タグの一致数
        if tag_ids:
            related = related.annotate(
                matching_tags=Count('tags', filter=Q(tags__id__in=tag_ids)),
                genre_score=genre_match,
                creator_score=creator_match
            ).annotate(
                relevance_score=F('matching_tags') * 3 + F('genre_score') + F('creator_score')
            ).order_by('-relevance_score', '-likes_count', '-created_at')
        else:
            # タグがない場合はジャンルと作成者でスコアリング
            related = related.annotate(
                genre_score=genre_match,
                creator_score=creator_match
            ).annotate(
                relevance_score=F('genre_score') + F('creator_score')
            ).order_by('-relevance_score', '-likes_count', '-created_at')
        
        return related.select_related('created_by')[:5]

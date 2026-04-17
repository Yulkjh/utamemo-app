from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.http import JsonResponse
from django.db.models import F

from ..models import Song, FlashcardDeck, Flashcard
from ..ai_services import GeminiFlashcardExtractor
import json
import logging

logger = logging.getLogger(__name__)

@login_required
def flashcard_list(request):
    """フラッシュカード デッキ一覧"""
    from ..models import FlashcardDeck
    decks = FlashcardDeck.objects.filter(user=request.user).select_related('source_song').prefetch_related('flashcards')
    
    # 各デッキの学習進捗を計算
    for deck in decks:
        selected = deck.flashcards.filter(is_selected=True)
        deck.total_selected = selected.count()
        deck.mastered_count = selected.filter(mastery_level=3).count()
        if deck.total_selected > 0:
            deck.progress_percent = int(deck.mastered_count / deck.total_selected * 100)
        else:
            deck.progress_percent = 0
    
    return render(request, 'songs/flashcard_list.html', {
        'decks': decks,
    })


@login_required
def flashcard_create_from_song(request, pk):
    """楽曲から暗記カードを作成"""
    from ..models import FlashcardDeck, Flashcard, Song
    from ..ai_services import GeminiFlashcardExtractor, GeminiOCR
    
    song = get_object_or_404(Song, pk=pk, created_by=request.user)
    
    # 既にこの楽曲の暗記カードがある場合はそちらにリダイレクト
    existing_deck = FlashcardDeck.objects.filter(source_song=song, user=request.user).first()
    if existing_deck:
        return redirect('songs:flashcard_select', pk=existing_deck.pk)
    
    if request.method != 'POST':
        return redirect('songs:song_detail', pk=pk)
    
    extractor = GeminiFlashcardExtractor()
    all_terms = []
    source_image_obj = None
    source_text = ''
    
    # 歌詞のオリジナルテキストを取得
    try:
        if hasattr(song, 'lyrics') and song.lyrics:
            source_text = song.lyrics.original_text or ''
    except Exception:
        pass
    
    # 1. 元画像がある場合 → 画像から直接抽出
    if song.source_image:
        try:
            source_image_obj = song.source_image
            terms = extractor.extract_terms_from_image(song.source_image.image)
            if terms:
                all_terms.extend(terms)
        except Exception as e:
            logger.warning(f"Flashcard image extraction error: {e}")
    
    # 2. 画像から取れなかった場合 → テキストから抽出
    if not all_terms and source_text:
        terms = extractor.extract_terms_from_text(source_text)
        if terms:
            all_terms.extend(terms)
    
    if not all_terms:
        app_language = request.session.get('app_language', 'ja')
        if app_language == 'en':
            messages.warning(request, 'Could not extract terms from this song.')
        elif app_language == 'zh':
            messages.warning(request, '无法从这首歌曲中提取术语。')
        else:
            messages.warning(request, 'この楽曲からキーワードを抽出できませんでした。')
        return redirect('songs:song_detail', pk=pk)
    
    # 重複除去
    seen = set()
    unique_terms = []
    for t in all_terms:
        key = t['term'].strip().lower()
        if key not in seen:
            seen.add(key)
            unique_terms.append(t)
    
    # デッキ作成
    deck = FlashcardDeck.objects.create(
        user=request.user,
        title=f'{song.title} の暗記カード',
        source_song=song,
        source_image=source_image_obj,
        source_text=source_text[:5000] if source_text else '',
    )
    
    for i, t in enumerate(unique_terms):
        importance = t.get('importance', 'normal')
        Flashcard.objects.create(
            deck=deck,
            term=t['term'],
            definition=t['definition'],
            importance=importance,
            is_selected=(importance == 'high'),
            order=i,
        )
    
    return redirect('songs:flashcard_select', pk=deck.pk)


@login_required
def flashcard_select(request, pk):
    """用語の選択・厳選画面"""
    from ..models import FlashcardDeck, Flashcard
    
    deck = get_object_or_404(FlashcardDeck.objects.select_related('source_song'), pk=pk, user=request.user)
    flashcards = deck.flashcards.all()
    
    if request.method == 'POST':
        # 選択された用語のIDリストを取得
        selected_ids = request.POST.getlist('selected_cards')
        selected_ids = [int(x) for x in selected_ids if x.isdigit()]
        
        # 全カードの選択状態を更新
        deck.flashcards.update(is_selected=False)
        if selected_ids:
            deck.flashcards.filter(id__in=selected_ids).update(is_selected=True)
        
        deck.update_card_count()
        
        if deck.card_count > 0:
            messages.success(request, f'{deck.card_count}枚のカードでデッキを作成しました！')
            return redirect('songs:flashcard_study', pk=deck.pk)
        else:
            messages.warning(request, 'カードを1枚以上選択してください。')
    
    return render(request, 'songs/flashcard_select.html', {
        'deck': deck,
        'flashcards': flashcards,
    })


@login_required
def flashcard_study(request, pk):
    """フラッシュカード学習画面"""
    from ..models import FlashcardDeck
    
    deck = get_object_or_404(FlashcardDeck, pk=pk, user=request.user)
    cards = deck.flashcards.filter(is_selected=True)
    
    if not cards.exists():
        messages.warning(request, 'このデッキにはカードがありません。')
        return redirect('songs:flashcard_select', pk=deck.pk)
    
    # カードデータをJSON化（JSで使用）
    cards_data = list(cards.values('id', 'term', 'definition', 'mastery_level', 'order'))
    
    return render(request, 'songs/flashcard_study.html', {
        'deck': deck,
        'cards': cards,
        'cards_json': json.dumps(cards_data, ensure_ascii=False),
        'total_cards': cards.count(),
        'mastered_count': cards.filter(mastery_level=3).count(),
    })


@login_required
@require_POST
def flashcard_update_mastery(request, pk):
    """カードの習熟度を更新（AJAX）"""
    from ..models import Flashcard
    
    try:
        data = json.loads(request.body)
        card_id = data.get('card_id')
        mastery = data.get('mastery_level', 0)
        
        card = get_object_or_404(Flashcard, pk=card_id, deck__pk=pk, deck__user=request.user)
        card.mastery_level = max(0, min(3, int(mastery)))
        card.save(update_fields=['mastery_level'])
        
        # デッキ全体の進捗を返す
        deck = card.deck
        selected = deck.flashcards.filter(is_selected=True)
        mastered = selected.filter(mastery_level=3).count()
        total = selected.count()
        
        return JsonResponse({
            'success': True,
            'mastery_level': card.mastery_level,
            'mastered_count': mastered,
            'total_cards': total,
            'progress_percent': int(mastered / total * 100) if total > 0 else 0,
        })
    except Exception as e:
        logger.error(f"Flashcard mastery update error: {e}")
        return JsonResponse({'success': False, 'error': 'An error occurred.'}, status=400)


@login_required
@require_POST
def flashcard_deck_delete(request, pk):
    """デッキを削除"""
    from ..models import FlashcardDeck
    
    deck = get_object_or_404(FlashcardDeck, pk=pk, user=request.user)
    deck.delete()
    messages.success(request, 'デッキを削除しました。')
    return redirect('songs:flashcard_list')


# =============================================================================

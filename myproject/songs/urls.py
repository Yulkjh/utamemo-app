from django.urls import path
from . import views

app_name = 'songs'

urlpatterns = [
    path('', views.HomeView.as_view(), name='home'),
    path('songs/', views.SongListView.as_view(), name='song_list'),
    path('songs/<int:pk>/', views.SongDetailView.as_view(), name='song_detail'),
    path('s/<str:share_id>/', views.song_share_redirect, name='song_share'),
    path('create/', views.CreateSongView.as_view(), name='create_song'),
    path('upload/', views.UploadImageView.as_view(), name='upload_image'),
    path('extraction-result/', views.TextExtractionResultView.as_view(), name='text_extraction_result'),
    path('lyrics-confirmation/', views.LyricsConfirmationView.as_view(), name='lyrics_confirmation'),
    path('reset-lyrics/', views.reset_lyrics_session, name='reset_lyrics_session'),
    path('lyrics-generating/', views.LyricsGeneratingView.as_view(), name='lyrics_generating'),
    path('api/generate-lyrics/', views.generate_lyrics_api, name='generate_lyrics_api'),
    path('my-songs/', views.MySongsView.as_view(), name='my_songs'),
    path('songs/<int:pk>/like/', views.like_song, name='like_song'),
    path('songs/<int:pk>/favorite/', views.favorite_song, name='favorite_song'),
    path('songs/<int:pk>/delete/', views.delete_song, name='delete_song'),
    path('songs/<int:pk>/comment/', views.add_comment, name='add_comment'),
    path('songs/<int:pk>/play/', views.record_play, name='record_play'),
    path('songs/<int:pk>/toggle-privacy/', views.toggle_song_privacy, name='toggle_privacy'),
    path('songs/<int:pk>/tags/add/', views.add_tag_to_song, name='add_tag'),
    path('songs/<int:pk>/tags/remove/', views.remove_tag_from_song, name='remove_tag'),
    path('songs/<int:pk>/update-title/', views.update_song_title, name='update_title'),
    path('songs/<int:pk>/retry/', views.retry_song_generation, name='retry_song'),
    path('songs/<int:pk>/generating/', views.song_generating, name='song_generating'),
    path('songs/<int:pk>/status/', views.check_song_status, name='check_song_status'),
    path('songs/<int:pk>/recreate/', views.recreate_with_lyrics, name='recreate_with_lyrics'),
    path('staff/api-status/', views.api_status_view, name='api_status'),
    path('set-language/<str:lang>/', views.set_language, name='set_language'),
    
    # クラス機能
    path('classroom/', views.classroom_list, name='classroom_list'),
    path('classroom/join/', views.classroom_join, name='classroom_join'),
    path('classroom/create/', views.classroom_create, name='classroom_create'),
    path('classroom/<int:pk>/', views.classroom_detail, name='classroom_detail'),
    path('classroom/<int:pk>/share/', views.classroom_share_song, name='classroom_share_song'),
    path('classroom/<int:pk>/leave/', views.classroom_leave, name='classroom_leave'),
    path('classroom/<int:pk>/delete/', views.classroom_delete, name='classroom_delete'),
    
    # 音声プロキシ（CORS対策）
    path('songs/<int:pk>/audio-proxy/', views.audio_proxy, name='audio_proxy'),
    
    # Mureka APIデバッグ（管理者のみ）
    path('staff/mureka-debug/', views.mureka_api_debug, name='mureka_debug'),
    
    # 曲クオリティチェック（管理者のみ）
    path('staff/quality-check/', views.quality_check, name='quality_check'),
    
    # コンテンツ違反ページ
    path('content-violation/', views.content_violation_view, name='content_violation'),
    
    # フラッシュカード機能
    path('flashcards/', views.flashcard_list, name='flashcard_list'),
    path('songs/<int:pk>/flashcards/create/', views.flashcard_create_from_song, name='flashcard_create_from_song'),
    path('flashcards/<int:pk>/select/', views.flashcard_select, name='flashcard_select'),
    path('flashcards/<int:pk>/study/', views.flashcard_study, name='flashcard_study'),
    path('flashcards/<int:pk>/mastery/', views.flashcard_update_mastery, name='flashcard_update_mastery'),
    path('flashcards/<int:pk>/delete/', views.flashcard_deck_delete, name='flashcard_deck_delete'),
    
    # トレーニング監視
    path('staff/training/', views.training_dashboard, name='training_dashboard'),
    path('staff/training-data/', views.training_data_viewer, name='training_data_viewer'),
    path('staff/training-history/', views.training_history, name='training_history'),
    path('api/training/data/', views.training_data_api, name='training_data_api'),
    path('api/training/data/generate/', views.training_data_generate, name='training_data_generate'),
    path('api/training/prompt/', views.training_prompt_api, name='training_prompt_api'),
    path('staff/llm-guide/', views.llm_guide, name='llm_guide'),
    path('staff/test-llm/', views.test_llm_page, name='test_llm'),
    path('staff/test-mureka/', views.test_mureka_page, name='test_mureka'),
    path('api/llm/health/', views.test_llm_health, name='test_llm_health'),
    path('api/llm/generate/', views.test_llm_generate, name='test_llm_generate'),
    path('api/mureka/test-submit/', views.test_mureka_submit, name='test_mureka_submit'),
    path('api/mureka/test-poll/', views.test_mureka_poll, name='test_mureka_poll'),
    path('api/training/update/', views.training_api_update, name='training_api_update'),
    path('api/training/reviewed/', views.training_reviewed_indices, name='training_reviewed_indices'),
    path('api/training/status/', views.training_api_status_json, name='training_api_status'),
    path('api/training/command/', views.training_send_command, name='training_send_command'),
]
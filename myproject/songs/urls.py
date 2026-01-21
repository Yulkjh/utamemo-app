from django.urls import path
from . import views

app_name = 'songs'

urlpatterns = [
    path('', views.HomeView.as_view(), name='home'),
    path('songs/', views.SongListView.as_view(), name='song_list'),
    path('songs/<int:pk>/', views.SongDetailView.as_view(), name='song_detail'),
    path('create/', views.CreateSongView.as_view(), name='create_song'),
    path('upload/', views.UploadImageView.as_view(), name='upload_image'),
    path('extraction-result/', views.TextExtractionResultView.as_view(), name='text_extraction_result'),
    path('lyrics-confirmation/', views.LyricsConfirmationView.as_view(), name='lyrics_confirmation'),
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
    path('songs/<int:pk>/status/', views.check_song_status, name='check_song_status'),
    path('admin/api-status/', views.api_status_view, name='api_status'),
    path('set-language/<str:lang>/', views.set_language, name='set_language'),
    
    # クラス機能
    path('classroom/', views.classroom_list, name='classroom_list'),
    path('classroom/join/', views.classroom_join, name='classroom_join'),
    path('classroom/create/', views.classroom_create, name='classroom_create'),
    path('classroom/<int:pk>/', views.classroom_detail, name='classroom_detail'),
    path('classroom/<int:pk>/share/', views.classroom_share_song, name='classroom_share_song'),
    path('classroom/<int:pk>/leave/', views.classroom_leave, name='classroom_leave'),
    path('classroom/<int:pk>/delete/', views.classroom_delete, name='classroom_delete'),
]
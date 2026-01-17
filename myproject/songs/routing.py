from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    re_path(r'ws/song/(?P<song_id>\d+)/progress/$', consumers.SongProgressConsumer.as_asgi()),
]

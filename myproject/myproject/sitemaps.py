from django.contrib.sitemaps import Sitemap
from django.urls import reverse
from songs.models import Song


class StaticViewSitemap(Sitemap):
    """静的ページのサイトマップ"""
    priority = 0.8
    changefreq = 'weekly'

    def items(self):
        return ['songs:home', 'songs:song_list', 'songs:upload_image']

    def location(self, item):
        return reverse(item)


class SongSitemap(Sitemap):
    """公開楽曲のサイトマップ"""
    changefreq = 'weekly'
    priority = 0.6

    def items(self):
        return Song.objects.filter(is_public=True, generation_status='completed')

    def lastmod(self, obj):
        return obj.updated_at if hasattr(obj, 'updated_at') else obj.created_at

    def location(self, obj):
        return reverse('songs:song_detail', args=[obj.id])

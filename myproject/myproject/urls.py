"""
URL configuration for myproject project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.sitemaps.views import sitemap
from django.http import HttpResponse
from django.views.decorators.cache import cache_page
from .media_views import serve_protected_media
from .legal_views import terms, privacy, contact, tokushoho
from .sitemaps import StaticViewSitemap, SongSitemap
from .security_views import admin_2fa_verify

sitemaps = {
    'static': StaticViewSitemap,
    'songs': SongSitemap,
}

@cache_page(60 * 60 * 24)
def robots_txt(request):
    lines = [
        "User-agent: *",
        "Allow: /",
        "",
        "Sitemap: https://utamemo.com/sitemap.xml",
    ]
    return HttpResponse("\n".join(lines), content_type="text/plain")

urlpatterns = [
    path('admin/2fa/', admin_2fa_verify, name='admin_2fa_verify'),
    path('admin/', admin.site.urls),
    path('robots.txt', robots_txt, name='robots_txt'),
    path('sitemap.xml', sitemap, {'sitemaps': sitemaps}, name='django.contrib.sitemaps.views.sitemap'),
    path('', include('songs.urls')),
    path('users/', include('users.urls')),
    path('terms/', terms, name='terms'),
    path('privacy/', privacy, name='privacy'),
    path('contact/', contact, name='contact'),
    path('tokushoho/', tokushoho, name='tokushoho'),
    re_path(r'^media/(?P<path>.*)$', serve_protected_media, name='protected_media'),
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATICFILES_DIRS[0])

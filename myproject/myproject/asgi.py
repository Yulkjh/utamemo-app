"""
myprojectプロジェクトのASGI設定。

``application``という名前のモジュールレベル変数としてASGI callableを公開します。

詳細はこちらを参照:
https://docs.djangoproject.com/en/5.2/howto/deployment/asgi/
"""

import os
from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'myproject.settings')

# ORMモデルをインポートする可能性のあるコードをインポートする前に
# AppRegistryが設定されるよう、Django ASGIアプリケーションを早期に初期化
django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
from channels.security.websocket import AllowedHostsOriginValidator
from songs import routing

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": AllowedHostsOriginValidator(
        AuthMiddlewareStack(
            URLRouter(
                routing.websocket_urlpatterns
            )
        )
    ),
})

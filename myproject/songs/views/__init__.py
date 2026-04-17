# songs/views/__init__.py
# 機能別に分割されたビューモジュールを統合re-export
# urls.py の `from . import views` → `views.XXX` が引き続き動作する

from .core import *          # noqa: F401, F403
from .classroom import *     # noqa: F401, F403
from .flashcard import *     # noqa: F401, F403
from .training import *      # noqa: F401, F403
from .staff import *         # noqa: F401, F403

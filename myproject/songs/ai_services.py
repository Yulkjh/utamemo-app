# songs/ai_services.py — 後方互換 re-export shim
#
# 2,966行あったモノリシックファイルを songs/services/ パッケージに分割。
# 既存の import を壊さないよう、すべてのシンボルをここから re-export する。
#
# 新規コードでは `from songs.services import ...` を推奨。

from .services import *  # noqa: F401,F403

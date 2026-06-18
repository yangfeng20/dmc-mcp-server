from __future__ import annotations

import os

DEFAULT_COOKIE_ENV = "DMC_COOKIE"


class CookieManager:
    def __init__(self):
        self._cookie: str = ""

    def load_from_env(self, key: str = DEFAULT_COOKIE_ENV) -> bool:
        val = os.environ.get(key, "").strip()
        if val:
            self._cookie = val
            return True
        return False

    def set_cookie(self, cookie: str):
        self._cookie = cookie.strip()

    @property
    def cookie(self) -> str:
        if not self._cookie:
            self.load_from_env()
        return self._cookie

    def is_ready(self) -> bool:
        return bool(self._cookie)

    def clear(self):
        self._cookie = ""

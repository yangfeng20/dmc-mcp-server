from __future__ import annotations

import os

DEFAULT_COOKIE_ENV = "DMC_COOKIE"
DEFAULT_MC_GTK_ENV = "DMC_MC_GTK"


class CookieManager:
    def __init__(self):
        self._cookie: str = ""
        self._mc_gtk: int = 0

    def load_from_env(self, key: str = DEFAULT_COOKIE_ENV) -> bool:
        val = os.environ.get(key, "").strip()
        if val:
            self._cookie = val
            return True
        return False

    def load_mc_gtk_from_env(self, key: str = DEFAULT_MC_GTK_ENV) -> bool:
        val = os.environ.get(key, "").strip()
        if val:
            try:
                self._mc_gtk = int(val)
                return True
            except ValueError:
                pass
        return False

    def set_cookie(self, cookie: str, mc_gtk: int = 0):
        self._cookie = cookie.strip()
        if mc_gtk:
            self._mc_gtk = mc_gtk

    @property
    def cookie(self) -> str:
        if not self._cookie:
            self.load_from_env()
        return self._cookie

    @property
    def mc_gtk(self) -> int:
        if not self._mc_gtk:
            self.load_mc_gtk_from_env()
        return self._mc_gtk

    def is_ready(self) -> bool:
        return bool(self._cookie)

    def clear(self):
        self._cookie = ""
        self._mc_gtk = 0

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from .storage import CookieStore

DEFAULT_COOKIE_ENV = "DMC_COOKIE"
DEFAULT_MC_GTK_ENV = "DMC_MC_GTK"


class CookieManager:
    """Thin wrapper around the persistent :class:`CookieStore`.

    Keeps the same public surface as the previous in-memory implementation
    (``set_cookie`` / ``cookie`` / ``mc_gtk`` / ``is_ready`` / ``clear``) so
    ``main.py`` and ``client.py`` stay compatible, while adding persistence
    and account+region awareness.

    The active cookie (most recently set) is preferred; callers that know a
    target region can request it explicitly via :meth:`get_for_region`.
    """

    def __init__(self, base_dir: Path | None = None):
        self._store = CookieStore(base_dir)
        self._env_cookie: str = ""
        self._env_mc_gtk: int = 0
        self._env_loaded = False
        # On startup, restore the most recent persisted cookie as active so
        # that a freshly-started process can query without re-setting a cookie.
        self._restore_active_from_disk()

    def _restore_active_from_disk(self) -> None:
        """Set the most recently stored cookie as the active one."""
        rows = self._store.list()
        if not rows:
            return
        newest = max(rows, key=lambda r: r.get("set_at", 0))
        key = newest["key"]
        cookie = self._store.get_cookie(key=key)
        if cookie:
            self._store._active_key = key
            self._store._active_cookie = cookie
            self._store._active_mc_gtk = 0

    # ------------------------------------------------------------------
    # Environment fallback (unchanged semantics)
    # ------------------------------------------------------------------
    def load_from_env(self, key: str = DEFAULT_COOKIE_ENV) -> bool:
        val = os.environ.get(key, "").strip()
        if val:
            self._env_cookie = val
            return True
        return False

    def load_mc_gtk_from_env(self, key: str = DEFAULT_MC_GTK_ENV) -> bool:
        val = os.environ.get(key, "").strip()
        if val:
            try:
                self._env_mc_gtk = int(val)
                return True
            except ValueError:
                pass
        return False

    # ------------------------------------------------------------------
    # Public surface (compatible with old API)
    # ------------------------------------------------------------------
    def set_cookie(self, cookie: str, mc_gtk: int = 0) -> str:
        """Persist a cookie (and mark it active).

        Returns:
            A human-readable confirmation including the resolved account key.
        """
        key, uin, region_id = self._store.set_cookie(cookie, mc_gtk)
        if key == "memory":
            return (
                "Cookie set in memory (could not parse uin/regionId from cookie; "
                "not persisted). Please ensure the cookie is from a Tencent console page."
            )
        return (
            f"Cookie saved for account {uin} / region_id={region_id} "
            f"(key={key}). It is now the active cookie."
        )

    @property
    def cookie(self) -> str:
        if self._store.get_cookie():
            return self._store.get_cookie()
        if not self._env_loaded:
            self._env_loaded = True
            self.load_from_env()
        return self._env_cookie or ""

    @property
    def mc_gtk(self) -> int:
        stored = self._store.get_mc_gtk()
        if stored:
            return stored
        if not self._env_loaded:
            self._env_loaded = True
            self.load_mc_gtk_from_env()
        return self._env_mc_gtk or 0

    def is_ready(self) -> bool:
        return bool(self._store.get_cookie() or self.cookie)

    def clear(self) -> None:
        self._store.clear()

    # ------------------------------------------------------------------
    # New: account/region-aware helpers for main.py / client.py
    # ------------------------------------------------------------------
    def get_for_region(self, region_id: int | None = None, region: str | None = None) -> str | None:
        """Return the best cookie for a target region.

        When a target region is given, only a cookie whose region matches will
        be returned (strict match, no fallback to the active cookie) -- this
        prevents silently using a Shanghai cookie when Singapore was requested.

        Args:
            region_id: Numeric Tencent region id (4=Shanghai, 9=Singapore).
            region: Region alias like ``ap-singapore`` (used to derive region_id).

        Returns:
            Cookie string or None.
        """
        rid = region_id
        if rid is None and region:
            rid = self._region_alias_to_id(region)
        if rid is not None:
            key = self._store._find_key_by_region(rid)
            if key:
                return self._store.get_cookie(key)
            return None  # strict: correct region not stored → no fallback
        return self._store.get_cookie()

    @staticmethod
    def _region_alias_to_id(region: str) -> int | None:
        """Map a region alias (``ap-singapore``) to region_id when possible."""
        alias = (region or "").strip().lower()
        table = {
            "ap-beijing": 1,
            "ap-shanghai": 4,
            "ap-guangzhou": 7,
            "ap-shenzhen": 11,
            "ap-chengdu": 16,
            "ap-chongqing": 23,
            "ap-nanjing": 45,
            "ap-hongkong": 21,
            "ap-singapore": 9,   # verified by parsing cookie regionId (README says 15, wrong)
            "na-siliconvalley": 13,
            "eu-frankfurt": 17,
        }
        return table.get(alias)

    @property
    def active_key(self) -> str | None:
        """Key ({uin}_{region_id}) of the currently active cookie, if any."""
        return self._store._active_key

    def list_stored(self) -> list[dict]:
        """List persisted cookies (for ``list_cookies`` tool)."""
        return self._store.list()

    def clear_region(self, region_id: int | None = None) -> list[str]:
        """Clear stored cookie(s) for a region (or the active one if None)."""
        return self._store.clear(region_id=region_id)

    @property
    def store(self) -> CookieStore:
        return self._store

"""Persistent, account-scoped storage for Tencent Cloud DMC cookies and creds.

Why account-scoped?
    The same browser may hold multiple Tencent Cloud accounts (e.g. a Shanghai
    account and a Singapore account) and the same agent fleet may query both.
    Cookies and DB credentials are therefore stored **per (uin, region_id)**,
    so that switching environments never silently reuses the wrong cookie.

Layout under ``~/.dmc-mcp-server/``::

    ~/.dmc-mcp-server/
    ├── key.bin                              # Fernet key for creds encryption
    ├── index.json                           # metadata for every stored cookie
    ├── cookie/
    │   ├── o100000000001_9.cookie           # example account, region_id=9
    │   └── o100000000002_4.cookie           # example account, region_id=4
    └── creds/
        └── o100000000001_9.json             # encrypted DB credentials
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Optional

from .crypto_local import LocalCrypto

_DEFAULT_BASE_DIR = Path.home() / ".dmc-mcp-server"
_COOKIE_TTL_SECONDS = 2 * 3600  # Tencent console cookie lifetime (~2h)


class CookieStore:
    """Persist and retrieve Tencent Cloud console cookies by account+region.

    Each stored cookie is keyed by ``{uin}_{region_id}`` parsed from the cookie
    itself, so accounts and regions never mix.
    """

    def __init__(self, base_dir: Path | None = None):
        self._base_dir = base_dir or _DEFAULT_BASE_DIR
        self._cookie_dir = self._base_dir / "cookie"
        self._index_path = self._base_dir / "index.json"
        self._index: dict[str, dict] = self._load_index()
        # In-process cache of the active (most recently set) cookie.
        self._active_key: str | None = None
        self._active_cookie: str = ""
        self._active_mc_gtk: int = 0

    # ------------------------------------------------------------------
    # Index
    # ------------------------------------------------------------------
    def _load_index(self) -> dict[str, dict]:
        if self._index_path.exists():
            try:
                return json.loads(self._index_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return {}
        return {}

    def _save_index(self) -> None:
        self._base_dir.mkdir(parents=True, exist_ok=True)
        tmp = self._index_path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(self._index, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(self._index_path)

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------
    @staticmethod
    def parse_uin(cookie: str) -> str | None:
        """Extract the account uin from a Tencent console cookie string.

        The cookie may carry the value as ``uin=o100000000001`` or
        ``uin=10044966718``; we normalize to ``o<digits>`` when missing the ``o``
        prefix is not present, but we keep whatever the cookie actually had.

        Args:
            cookie: Raw cookie string from ``document.cookie``.

        Returns:
            The uin value, or None if it cannot be found.
        """
        m = re.search(r"(?:^|;\s*)uin=([^;]+)", cookie)
        if not m:
            return None
        val = m.group(1).strip()
        return val or None

    @staticmethod
    def parse_region_id(cookie: str) -> int | None:
        """Extract the numeric region id from a Tencent console cookie.

        Args:
            cookie: Raw cookie string.

        Returns:
            region_id int, or None if absent/not numeric.
        """
        m = re.search(r"(?:^|;\s*)regionId=([0-9]+)", cookie)
        if not m:
            return None
        try:
            return int(m.group(1))
        except ValueError:
            return None

    @staticmethod
    def make_key(uin: str, region_id: int) -> str:
        return f"{uin}_{region_id}"

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------
    def set_cookie(self, cookie: str, mc_gtk: int = 0) -> tuple[str, str | None, int | None]:
        """Persist a cookie and mark it active.

        Args:
            cookie: Full Tencent console cookie string.
            mc_gtk: Optional csrfCode.

        Returns:
            (key, uin, region_id) where key is like ``o..._9``.
            uin/region_id are None if they could not be parsed from the cookie
            (in which case nothing is persisted and only the in-memory value is set).
        """
        uin = self.parse_uin(cookie)
        region_id = self.parse_region_id(cookie)

        if uin is None or region_id is None:
            # Cannot key it → keep in-memory only (backward compat).
            self._active_key = None
            self._active_cookie = cookie
            self._active_mc_gtk = mc_gtk
            return ("memory", uin, region_id)

        key = self.make_key(uin, region_id)
        self._cookie_dir.mkdir(parents=True, exist_ok=True)
        (self._cookie_dir / f"{key}.cookie").write_text(cookie, encoding="utf-8")

        self._index[key] = {
            "uin": uin,
            "region_id": region_id,
            "set_at": int(time.time()),
            "mc_gtk": mc_gtk,
            "source": "set_cookie",
        }
        self._save_index()

        self._active_key = key
        self._active_cookie = cookie
        self._active_mc_gtk = mc_gtk
        return (key, uin, region_id)

    def get_cookie(self, key: str | None = None, region_id: int | None = None) -> str | None:
        """Get a cookie, preferring the active one unless a target is given.

        Args:
            key: Explicit ``{uin}_{region_id}`` key to fetch.
            region_id: If given, fetch the most recent cookie for that region.

        Returns:
            The cookie string, or None if not found.
        """
        if key is None and region_id is not None:
            key = self._find_key_by_region(region_id)
        if key is None:
            return self._active_cookie or None
        if key == self._active_key and self._active_cookie:
            return self._active_cookie

        path = self._cookie_dir / f"{key}.cookie"
        if not path.exists():
            return None
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            return None

    def get_mc_gtk(self, key: str | None = None, region_id: int | None = None) -> int:
        """Return the stored mc_gtk for the resolved key (0 if unknown).

        Prefers the in-memory active value; falls back to the persisted index
        entry so a freshly-restarted process keeps a working csrfCode.
        """
        if key is None and region_id is not None:
            key = self._find_key_by_region(region_id)
        if key is None:
            return self._active_mc_gtk
        if key == self._active_key and self._active_mc_gtk:
            return self._active_mc_gtk
        meta = self._index.get(key)
        return int(meta.get("mc_gtk", 0) or 0) if meta else 0

    def _find_key_by_region(self, region_id: int) -> str | None:
        matches = [
            k for k, meta in self._index.items()
            if meta.get("region_id") == region_id
        ]
        if not matches:
            return None
        # Most recently set wins.
        matches.sort(key=lambda k: self._index[k].get("set_at", 0), reverse=True)
        return matches[0]

    def is_expired(self, key: str) -> bool:
        """True if the stored cookie for ``key`` is older than the TTL."""
        meta = self._index.get(key)
        if not meta:
            return False
        set_at = meta.get("set_at", 0)
        return (time.time() - set_at) > _COOKIE_TTL_SECONDS

    def list(self) -> list[dict]:
        """List all stored cookies with metadata (for ``list_cookies``)."""
        rows = []
        for key, meta in self._index.items():
            rows.append(
                {
                    "key": key,
                    "uin": meta.get("uin"),
                    "region_id": meta.get("region_id"),
                    "set_at": meta.get("set_at"),
                    "age_seconds": int(time.time() - meta.get("set_at", 0)),
                    "expired": self.is_expired(key),
                }
            )
        return rows

    def clear(self, key: str | None = None, region_id: int | None = None) -> list[str]:
        """Delete stored cookie(s). Returns the keys that were removed."""
        if key is None and region_id is not None:
            found = self._find_key_by_region(region_id)
            key = found
        if key is None:
            return []

        removed = []
        if key in self._index:
            path = self._cookie_dir / f"{key}.cookie"
            if path.exists():
                path.unlink()
            self._index.pop(key, None)
            self._save_index()
            removed.append(key)
            if self._active_key == key:
                self._active_key = None
                self._active_cookie = ""
                self._active_mc_gtk = 0
        return removed


class CredentialStore:
    """Encrypted-at-rest store of DB credentials for logged-in instances.

    Keyed by instance_id so ``login_instance`` can reuse the password without
    the agent re-supplying it. Scoped under the same account key as the cookie
    that was active at login time.
    """

    def __init__(self, base_dir: Path | None = None):
        self._base_dir = base_dir or _DEFAULT_BASE_DIR
        self._creds_dir = self._base_dir / "creds"
        self._crypto = LocalCrypto(base_dir)

    def _account_file(self, account_key: str) -> Path:
        return self._creds_dir / f"{account_key}.json"

    def save(
        self,
        account_key: str,
        instance_id: str,
        user: str,
        password: str,
        db_type: str,
        region_id: int,
    ) -> None:
        """Store credentials for one instance under an account key."""
        self._creds_dir.mkdir(parents=True, exist_ok=True)
        data: dict = {}
        path = self._account_file(account_key)
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                data = {}

        data[instance_id] = {
            "user": user,
            "password_enc": self._crypto.encrypt(password),
            "db_type": db_type,
            "region_id": region_id,
            "saved_at": int(time.time()),
        }
        tmp = path.with_suffix(".tmp.json")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

    def get(self, account_key: str, instance_id: str) -> dict | None:
        """Return decrypted creds for an instance, or None."""
        path = self._account_file(account_key)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        entry = data.get(instance_id)
        if not entry:
            return None
        return {
            "user": entry.get("user"),
            "password": self._crypto.decrypt(entry["password_enc"]),
            "db_type": entry.get("db_type"),
            "region_id": entry.get("region_id"),
        }

    def list_account_keys(self) -> list[str]:
        if not self._creds_dir.exists():
            return []
        return [p.stem for p in self._creds_dir.glob("*.json")]

    def clear_account(self, account_key: str) -> bool:
        path = self._account_file(account_key)
        if path.exists():
            path.unlink()
            return True
        return False

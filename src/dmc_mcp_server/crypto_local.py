"""Local symmetric encryption for persisted credentials.

Unlike ``crypto.py`` (which uses Tencent Cloud's RSA public key for the DMC
login API), this module provides encryption that WE own the private key for.
It is used to encrypt database passwords at rest in ``~/.dmc-mcp-server/creds/``.

The key material is stored in ``~/.dmc-mcp-server/key.bin`` with restrictive
file permissions (owner-only on POSIX; on Windows it inherits the user's
default ACL for the home directory).
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

_KEY_FILE = "key.bin"
_DEFAULT_BASE_DIR = Path.home() / ".dmc-mcp-server"


def _ensure_key_file(base_dir: Path) -> bytes:
    """Load the Fernet key from disk, creating a fresh one if missing.

    Args:
        base_dir: Directory where the key file lives.

    Returns:
        The raw Fernet key bytes (URL-safe base64).
    """
    base_dir.mkdir(parents=True, exist_ok=True)
    key_path = base_dir / _KEY_FILE
    if key_path.exists():
        data = key_path.read_bytes()
        # Trim stray whitespace if any.
        key = data.strip()
        # Validate it parses as a Fernet key to catch corrupted files.
        try:
            Fernet(key)
        except (ValueError, InvalidToken):
            raise RuntimeError(
                f"Corrupted local encryption key at {key_path}. "
                f"Delete it and re-run to regenerate (old creds will be unrecoverable)."
            )
        return key

    key = Fernet.generate_key()
    key_path.write_bytes(key)
    # Restrict permissions on POSIX (Windows ACLs are inherited from the user profile).
    try:
        os.chmod(key_path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    return key


class LocalCrypto:
    """Encrypt / decrypt secrets using a locally-owned Fernet key."""

    def __init__(self, base_dir: Path | None = None):
        self._base_dir = base_dir or _DEFAULT_BASE_DIR
        self._fernet: Fernet | None = None

    @property
    def _f(self) -> Fernet:
        if self._fernet is None:
            self._fernet = Fernet(_ensure_key_file(self._base_dir))
        return self._fernet

    def encrypt(self, plaintext: str) -> str:
        """Encrypt a string, returning a URL-safe base64 token."""
        return self._f.encrypt(plaintext.encode("utf-8")).decode("ascii")

    def decrypt(self, token: str) -> str:
        """Decrypt a token back to the original string."""
        try:
            return self._f.decrypt(token.encode("ascii")).decode("utf-8")
        except (InvalidToken, ValueError) as exc:
            raise RuntimeError(
                "Failed to decrypt a stored credential. "
                "The local encryption key may have changed."
            ) from exc

"""Per-bot API keys, encrypted at rest outside the SQLite database.

Keys never enter ``bots.payload``, pin revisions, run snapshots, events or logs.
They live in ``<data_dir>/secrets/bot_keys.json`` as Fernet tokens; the master key
is ``<data_dir>/secrets/master.key`` (mode 0600, generated on first write).
The data directory is git-ignored.  Anyone who can read the whole data directory
can decrypt the keys, so this protects against accidental disclosure
(backups of the DB, exported payloads, logs), not against a compromised host.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

_LOCK = threading.Lock()


class BotSecretStore:
    def __init__(self, data_dir: Path) -> None:
        self.folder = Path(data_dir) / "secrets"
        self._keys = self.folder / "bot_keys.json"
        self._master = self.folder / "master.key"

    # -- internals ---------------------------------------------------------

    def _fernet(self, *, create: bool) -> Fernet | None:
        if self._master.exists():
            return Fernet(self._master.read_bytes().strip())
        if not create:
            return None
        self.folder.mkdir(parents=True, exist_ok=True)
        os.chmod(self.folder, 0o700)
        key = Fernet.generate_key()
        fd = os.open(self._master, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(key)
        return Fernet(key)

    def _read(self) -> dict[str, str]:
        if not self._keys.exists():
            return {}
        try:
            data = json.loads(self._keys.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _write(self, data: dict[str, str]) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        tmp = self._keys.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
        os.replace(tmp, self._keys)

    # -- public ------------------------------------------------------------

    def set(self, bot_id: str, api_key: str) -> None:
        with _LOCK:
            fernet = self._fernet(create=True)
            assert fernet is not None
            data = self._read()
            data[bot_id] = fernet.encrypt(api_key.encode("utf-8")).decode("ascii")
            self._write(data)

    def get(self, bot_id: str) -> str | None:
        with _LOCK:
            fernet = self._fernet(create=False)
            token = self._read().get(bot_id)
        if fernet is None or not token:
            return None
        try:
            return fernet.decrypt(token.encode("ascii")).decode("utf-8")
        except (InvalidToken, ValueError):
            return None

    def has(self, bot_id: str) -> bool:
        with _LOCK:
            return bot_id in self._read()

    def ids(self) -> set[str]:
        """Bot ids that have a stored key (never the keys themselves)."""
        with _LOCK:
            return set(self._read())

    def delete(self, bot_id: str) -> None:
        with _LOCK:
            data = self._read()
            if bot_id in data:
                del data[bot_id]
                self._write(data)


__all__ = ["BotSecretStore"]

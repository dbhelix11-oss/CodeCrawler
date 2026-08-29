"""Per-file trust for inspecting the modules a source file imports.

CodeCrawler never runs the file you are crawling. But to list what lives inside
a *third-party* module it imports (``numpy.array``, ``requests.get`` …) it has to
either read that module's own source (tier 3) or import it (tier 4, which runs
the module's top-level code). Both need your say-so, and the decision is
remembered — keyed by the absolute path of the file you were crawling — in
``<data_dir>/trust.json``.

Standard-library modules are trusted automatically (see
``[trust] stdlib`` in the config) and are served from bundled data, so they
never reach this store.

Trust tiers, as stored:
    3  read the module's ``.py`` source, parse it, list its names — no execution
    4  import the module and introspect it — executes its module-level code
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

TIER_SOURCE = 3
TIER_IMPORT = 4


def sha256_file(path: Path | str) -> str:
    """Hex digest of a file's bytes, or ``""`` if it cannot be read."""
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return ""


@dataclass
class ModuleTrust:
    tier: int
    module_sha256: str = ""  # set only for single-file local modules


@dataclass
class FileTrust:
    file_sha256: str = ""
    modules: dict[str, ModuleTrust] = field(default_factory=dict)

    def to_json(self) -> dict:
        return {
            "file_sha256": self.file_sha256,
            "modules": {
                name: {"tier": mt.tier, "module_sha256": mt.module_sha256}
                for name, mt in self.modules.items()
            },
        }

    @classmethod
    def from_json(cls, raw: dict) -> "FileTrust":
        mods: dict[str, ModuleTrust] = {}
        for name, m in (raw.get("modules") or {}).items():
            try:
                mods[name] = ModuleTrust(
                    tier=int(m.get("tier", TIER_SOURCE)),
                    module_sha256=str(m.get("module_sha256", "")),
                )
            except (TypeError, ValueError):
                continue
        return cls(file_sha256=str(raw.get("file_sha256", "")), modules=mods)


class TrustStore:
    """Reads and writes ``trust.json``. One instance per run."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self._data: dict[str, FileTrust] | None = None

    # -- disk ---------------------------------------------------------

    def _load(self) -> dict[str, FileTrust]:
        if self._data is not None:
            return self._data
        data: dict[str, FileTrust] = {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                for key, val in raw.items():
                    if isinstance(val, dict):
                        data[key] = FileTrust.from_json(val)
        except (OSError, ValueError):
            pass
        self._data = data
        return data

    def _save(self) -> None:
        data = self._load()
        payload = {k: v.to_json() for k, v in data.items()}
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(payload, indent=1, sort_keys=True) + "\n", encoding="utf-8"
            )
        except OSError:
            pass

    # -- queries ----------------------------------------------------

    @staticmethod
    def _key(file_path: Path | str) -> str:
        return str(Path(file_path).resolve())

    def for_file(self, file_path: Path | str) -> FileTrust:
        """Stored trust for ``file_path`` (an empty :class:`FileTrust` if none)."""
        return self._load().get(self._key(file_path), FileTrust())

    def record(
        self,
        file_path: Path | str,
        file_sha256: str,
        module: str,
        tier: int,
        module_sha256: str = "",
    ) -> None:
        """Persist that ``module`` is trusted at ``tier`` while crawling ``file_path``."""
        data = self._load()
        key = self._key(file_path)
        ft = data.get(key) or FileTrust()
        ft.file_sha256 = file_sha256
        ft.modules[module] = ModuleTrust(tier=tier, module_sha256=module_sha256)
        data[key] = ft
        self._save()

    def forget(self, file_path: Path | str, module: str) -> None:
        data = self._load()
        ft = data.get(self._key(file_path))
        if ft and module in ft.modules:
            del ft.modules[module]
            self._save()

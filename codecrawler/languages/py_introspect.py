"""Look inside a Python module the crawled file imports.

Two operations, matching the two manual trust tiers:

* :func:`read_source_members` — tier 3. Find the module's ``.py`` file(s) via
  :func:`importlib.util.find_spec` (which, for a top-level name, does *not*
  execute the module), parse them, and list the names defined at top level.
  No code from the module runs.

* :func:`import_members` — tier 4. ``import`` the module and read ``dir()``.
  This runs the module's top-level code.

Both are best-effort: they return ``None`` (or raise, for tier 4) rather than
guess.
"""

from __future__ import annotations

import ast
import importlib
import importlib.util
import inspect
from pathlib import Path

from .base import Member


def module_source_file(module: str) -> Path | None:
    """Path to a *single-file* module's ``.py`` (not a package), else ``None``.

    Used to fingerprint a local module so a later change can be flagged.
    """
    if "." in module:
        return None
    try:
        spec = importlib.util.find_spec(module)
    except (ImportError, ValueError, ModuleNotFoundError):
        return None
    if spec is None or not spec.origin or not spec.origin.endswith(".py"):
        return None
    if spec.submodule_search_locations:  # it's a package
        return None
    return Path(spec.origin)


def _names_from_all(tree: ast.Module) -> list[str] | None:
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets
        ):
            if isinstance(node.value, (ast.List, ast.Tuple)):
                out = [
                    el.value
                    for el in node.value.elts
                    if isinstance(el, ast.Constant) and isinstance(el.value, str)
                ]
                return out or None
    return None


def _top_level_defs(tree: ast.Module) -> list[Member]:
    out: list[Member] = []
    seen: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            kind = "func"
            name = node.name
        elif isinstance(node, ast.ClassDef):
            kind = "class"
            name = node.name
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and not t.id.startswith("_") and t.id not in seen:
                    seen.add(t.id)
                    out.append(Member(name=t.id, kind="attr"))
            continue
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            name, kind = node.target.id, "attr"
        else:
            continue
        if name.startswith("_") or name in seen:
            continue
        seen.add(name)
        out.append(Member(name=name, kind=kind))
    return out


def read_source_members(module: str) -> list[Member] | None:
    """Tier 3: parse the module's own source, list its top-level names.

    ``None`` when the source cannot be located (a C extension, a frozen module,
    or a dotted name we decline to resolve).
    """
    if "." in module:
        return None
    try:
        spec = importlib.util.find_spec(module)
    except (ImportError, ValueError, ModuleNotFoundError):
        return None
    if spec is None or not spec.origin or not spec.origin.endswith(".py"):
        return None

    files: list[Path] = [Path(spec.origin)]
    if spec.submodule_search_locations:  # a package — also glob its top level
        pkg_dir = Path(list(spec.submodule_search_locations)[0])
        files += sorted(p for p in pkg_dir.glob("*.py") if p.name != "__init__.py")

    members: dict[str, Member] = {}
    used_all = False
    for path in files:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, ValueError):
            continue
        names = _names_from_all(tree)
        if names is not None:
            used_all = True
            for n in names:
                members.setdefault(n, Member(name=n))
        for m in _top_level_defs(tree):
            members.setdefault(m.name, m)
        if path.name != "__init__.py":
            members.setdefault(path.stem, Member(name=path.stem, kind="submodule"))

    ordered = sorted(members.values(), key=lambda m: m.name.lower())
    # If __all__ was authoritative, drop private extras it did not list.
    if used_all:
        allowed = set()
        for path in files:
            try:
                names = _names_from_all(ast.parse(path.read_text(encoding="utf-8")))
            except (OSError, SyntaxError, ValueError):
                names = None
            if names:
                allowed.update(names)
        if allowed:
            ordered = [m for m in ordered if m.name in allowed]
    return ordered or None


def import_members(module: str) -> list[Member]:
    """Tier 4: import the module and introspect it. Runs its module-level code.

    Raises on import failure; the caller reports that to the user.
    """
    mod = importlib.import_module(module)
    out: list[Member] = []
    for name in sorted(dir(mod), key=str.lower):
        if name.startswith("_"):
            continue
        try:
            obj = getattr(mod, name)
        except Exception:
            out.append(Member(name=name))
            continue
        if inspect.isclass(obj):
            kind = "class"
        elif inspect.isfunction(obj) or inspect.isbuiltin(obj) or inspect.ismethoddescriptor(obj):
            kind = "func"
        elif inspect.ismodule(obj):
            kind = "submodule"
        else:
            kind = "attr"
        doc = inspect.getdoc(obj) or ""
        blurb = doc.strip().splitlines()[0][:100] if doc.strip() else ""
        out.append(Member(name=name, kind=kind, blurb=blurb))
    return out

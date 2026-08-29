"""Python analyzer: stdlib :mod:`tokenize` for the token stream, :mod:`ast` for
the role each punctuation token plays, and a small template layer that turns a
whole line into a sentence.
"""

from __future__ import annotations

import ast
import io
import json
import keyword
import sys
import token as _token
import tokenize
from dataclasses import dataclass
from importlib.resources import files as _res_files

from .base import Analysis, Analyzer, Member, NamespaceRef, Pos, Token

# ---------------------------------------------------------------------------
# operator-class -> (lexeme, role) tables
# ---------------------------------------------------------------------------

_BINOP = {
    "Add": ("+", "arithmetic"),
    "Sub": ("-", "arithmetic"),
    "Mult": ("*", "arithmetic"),
    "Div": ("/", "arithmetic"),
    "FloorDiv": ("//", "arithmetic"),
    "Mod": ("%", "arithmetic"),
    "Pow": ("**", "arithmetic"),
    "MatMult": ("@", "matmul"),
    "BitAnd": ("&", "bitwise"),
    "BitOr": ("|", "bitwise"),
    "BitXor": ("^", "bitwise"),
    "LShift": ("<<", "bitwise"),
    "RShift": (">>", "bitwise"),
}

_UNARY = {
    "USub": ("-", "unary"),
    "UAdd": ("+", "unary"),
    "Invert": ("~", "bitwise"),
}

_CMP = {
    "Eq": ("==", "comparison"),
    "NotEq": ("!=", "comparison"),
    "Lt": ("<", "comparison"),
    "LtE": ("<=", "comparison"),
    "Gt": (">", "comparison"),
    "GtE": (">=", "comparison"),
    "Is": ("is", ""),
    "IsNot": ("is", ""),
    "In": ("in", "membership"),
    "NotIn": ("in", "membership"),
}

_BLOCK_NODES = {
    "FunctionDef", "AsyncFunctionDef", "ClassDef", "If", "For", "AsyncFor",
    "While", "With", "AsyncWith", "Try", "TryStar", "ExceptHandler", "Match",
    "match_case",
}

_BINOP_WORD = {
    "Add": "plus", "Sub": "minus", "Mult": "times", "Div": "divided by",
    "FloorDiv": "floor-divided by", "Mod": "modulo", "Pow": "to the power of",
    "MatMult": "matrix-multiplied by", "BitAnd": "bitwise-and", "BitOr": "bitwise-or",
    "BitXor": "bitwise-xor", "LShift": "left-shifted by", "RShift": "right-shifted by",
}

_CMP_WORD = {
    "Eq": "equals", "NotEq": "is not equal to", "Lt": "is less than",
    "LtE": "is at most", "Gt": "is greater than", "GtE": "is at least",
    "Is": "is the same object as", "IsNot": "is not the same object as",
    "In": "is in", "NotIn": "is not in",
}


@dataclass
class _Raw:
    type: str  # normalized type
    raw_type: str  # original tokenize name (keeps FSTRING_* distinctions)
    string: str
    start: Pos
    end: Pos
    line: str


class PythonAnalyzer(Analyzer):
    name = "python"
    extensions = (".py", ".pyi", ".pyw")

    # -- public API ------------------------------------------------------

    def analyze(self, source: str) -> Analysis:
        raw, lex_error = self._lex(source)
        roles: dict[Pos, tuple[str, str]] = {}
        ok = True
        error = lex_error
        try:
            tree = ast.parse(source)
        except SyntaxError as exc:
            ok = False
            tree = None
            error = error or f"syntax error: {exc.msg} (line {exc.lineno})"
        if tree is not None:
            try:
                self._tag_roles(tree, raw, roles)
            except Exception:  # tagging is best-effort; never break tokenizing
                ok = False
        self._tag_fstring_fields(raw, roles)
        self._tag_decorators(raw, roles)

        refs: dict[Pos, str] = {}
        if tree is not None:
            try:
                self._tag_module_refs(tree, raw, refs)
            except Exception:  # ref tagging is best-effort
                refs = {}

        tokens: list[Token] = []
        for r in raw:
            lexeme, role, note = self._key_for(r, roles)
            tokens.append(
                Token(
                    type=r.type,
                    string=r.string,
                    start=r.start,
                    end=r.end,
                    line=r.line,
                    lexeme=lexeme,
                    role=role,
                    note=note,
                    concepts=tuple(_concepts_for(lexeme, r.type, role)),
                    ref=refs.get(r.start, ""),
                )
            )
        return Analysis(
            language=self.name, source=source, tokens=tokens, ok=ok, error=error
        )

    # -- namespaces / imports -------------------------------------

    @staticmethod
    def is_stdlib(module: str) -> bool:
        return module.split(".")[0] in sys.stdlib_module_names

    def module_members(self, module: str) -> list[Member] | None:
        data = _stdlib_data().get(module)
        if data is None:
            return None
        return [
            Member(name=n, blurb=b)
            for n, b in sorted(data.items(), key=lambda kv: kv[0].lower())
        ]

    @staticmethod
    def _module_bindings(tree: ast.AST) -> tuple[dict[str, str], dict[str, str]]:
        """``({local_name: dotted_module}, {imported_name: source_module})``."""
        bound: dict[str, str] = {}
        from_map: dict[str, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    bound[a.asname or a.name.split(".")[0]] = a.name
            elif isinstance(node, ast.ImportFrom) and not node.level:
                mod = node.module or ""
                for a in node.names:
                    if a.name != "*":
                        from_map[a.asname or a.name] = mod
        return bound, from_map

    def _tag_module_refs(self, tree, raw, refs: dict[Pos, str]) -> None:
        bound, _ = self._module_bindings(tree)
        if not bound:
            return
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Name)
                and isinstance(node.ctx, ast.Load)
                and node.id in bound
            ):
                refs[(node.lineno, node.col_offset)] = bound[node.id]
        import_lines: set[int] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for ln in range(node.lineno, (node.end_lineno or node.lineno) + 1):
                    import_lines.add(ln)
        head = {v.split(".")[0]: v for v in bound.values()}
        for r in raw:
            if r.start[0] in import_lines and r.type == "NAME":
                if r.string in bound:
                    refs.setdefault(r.start, bound[r.string])
                elif r.string in head:
                    refs.setdefault(r.start, head[r.string])

    def resolve_namespace(self, source: str, row: int, col: int) -> NamespaceRef | None:
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return None
        analysis = self.analyze(source)
        tok = analysis.token_at(row, col)
        if tok is None or tok.type not in ("NAME", "KEYWORD"):
            return None

        bound, from_map = self._module_bindings(tree)

        if tok.ref:
            return NamespaceRef(kind="module", owner=tok.ref, module=tok.ref)

        recv = self._attr_receiver(analysis, tok)
        if recv is not None:
            nsr = self._namespace_for_receiver(recv, bound, tree, row)
            if nsr is not None:
                return nsr

        if not self._is_attr_tail(analysis, tok):
            if tok.string in from_map and from_map[tok.string]:
                mod = from_map[tok.string]
                return NamespaceRef(
                    kind="module", owner=mod, module=mod, from_import=True
                )
            nsr = self._namespace_for_receiver(tok.string, bound, tree, row)
            if nsr is not None:
                return nsr
        return None

    @staticmethod
    def _prev_meaningful(analysis: Analysis, tok: Token) -> Token | None:
        prev = None
        for t in analysis.tokens:
            if t.start >= tok.start:
                break
            if not t.is_layout and t.type != "COMMENT":
                prev = t
        return prev

    def _is_attr_tail(self, analysis: Analysis, tok: Token) -> bool:
        p = self._prev_meaningful(analysis, tok)
        return p is not None and p.type == "OP" and p.string == "."

    def _attr_receiver(self, analysis: Analysis, tok: Token) -> str | None:
        """For ``a.b`` with the cursor on ``b``: return ``"a"`` (only one hop)."""
        dot = self._prev_meaningful(analysis, tok)
        if dot is None or dot.type != "OP" or dot.string != ".":
            return None
        recv = self._prev_meaningful(analysis, dot)
        if recv is None or recv.type not in ("NAME", "KEYWORD"):
            return None
        before = self._prev_meaningful(analysis, recv)
        if before is not None and before.type == "OP" and before.string == ".":
            return None  # deeper chain than we resolve
        return recv.string

    def _namespace_for_receiver(
        self, name: str, bound: dict[str, str], tree: ast.AST, row: int
    ) -> NamespaceRef | None:
        if name in bound:
            return NamespaceRef(kind="module", owner=name, module=bound[name])

        if name in ("self", "cls"):
            cls = self._enclosing_classdef(tree, row)
            if cls is not None:
                return NamespaceRef(
                    kind="namespace",
                    owner=f"{name} → {cls.name}",
                    members=self._class_members(cls),
                )
            return None

        cls = self._classdef_by_name(tree, name)
        if cls is not None:
            return NamespaceRef(
                kind="namespace", owner=cls.name, members=self._class_members(cls)
            )

        made = self._assigned_class(name, tree, row)
        if made is not None:
            return NamespaceRef(
                kind="namespace",
                owner=f"{name} → {made.name}",
                members=self._class_members(made),
            )
        return None

    @staticmethod
    def _enclosing_classdef(tree: ast.AST, row: int) -> ast.ClassDef | None:
        best = None
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                lo, hi = node.lineno, (node.end_lineno or node.lineno)
                if lo <= row <= hi and (
                    best is None or (hi - lo) < (best.end_lineno or best.lineno) - best.lineno
                ):
                    best = node
        return best

    @staticmethod
    def _classdef_by_name(tree: ast.AST, name: str) -> ast.ClassDef | None:
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == name:
                return node
        return None

    def _assigned_class(
        self, name: str, tree: ast.AST, row: int
    ) -> ast.ClassDef | None:
        """``name = SomeClass(...)`` where ``SomeClass`` is defined in this file."""
        classes = {
            n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)
        }
        hit: ast.ClassDef | None = None
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            if not any(
                isinstance(t, ast.Name) and t.id == name for t in node.targets
            ):
                continue
            val = node.value
            if (
                isinstance(val, ast.Call)
                and isinstance(val.func, ast.Name)
                and val.func.id in classes
            ):
                cand = self._classdef_by_name(tree, val.func.id)
                if cand is None:
                    continue
                # prefer an assignment at or before the cursor
                if node.lineno <= row or hit is None:
                    hit = cand
        return hit

    @staticmethod
    def _class_members(cls: ast.ClassDef) -> list[Member]:
        methods: list[Member] = []
        attrs: dict[str, Member] = {}
        for node in cls.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                methods.append(Member(name=node.name, kind="method"))
            elif isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        attrs.setdefault(t.id, Member(name=t.id, kind="attr"))
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                attrs.setdefault(node.target.id, Member(name=node.target.id, kind="attr"))
        for node in ast.walk(cls):
            tgts = []
            if isinstance(node, ast.Assign):
                tgts = node.targets
            elif isinstance(node, ast.AnnAssign):
                tgts = [node.target]
            for t in tgts:
                if (
                    isinstance(t, ast.Attribute)
                    and isinstance(t.value, ast.Name)
                    and t.value.id in ("self", "cls")
                ):
                    attrs.setdefault(t.attr, Member(name=t.attr, kind="attr"))
        methods.sort(key=lambda m: m.name.lower())
        return methods + sorted(attrs.values(), key=lambda m: m.name.lower())

    def describe_line(self, source: str, lineno: int) -> str:
        lines = source.splitlines()
        if lineno < 1 or lineno > len(lines):
            return "(no such line)"
        stripped = lines[lineno - 1].strip()
        if not stripped:
            return "Blank line — ignored by Python."
        if stripped.startswith("#"):
            return "A comment — everything after the # is ignored by Python."
        for prefix, text in _BARE_HEADERS.items():
            if stripped == prefix or stripped.rstrip(":").strip() == prefix.rstrip(":"):
                return text
        if stripped.startswith("except"):
            return (
                "Handles a matching exception from the try block above; "
                "`as name` binds the exception object for the block."
            )
        if stripped.startswith("@"):
            return (
                f"Decorator: wraps the function or class defined just below with "
                f"`{stripped[1:].strip()}` (i.e. name = {stripped[1:].strip()}(name))."
            )

        try:
            tree = ast.parse(source)
        except SyntaxError as exc:
            return f"`{stripped}` — the file does not parse ({exc.msg}), so no structural reading is available."

        exact = self._smallest_stmt_on_line(tree, lineno)
        if exact is not None:
            if isinstance(exact, ast.If) and stripped.startswith("elif"):
                return f"Else-if: only when every earlier condition was false, test whether {self._expr(exact.test)}."
            return self._describe_stmt(exact)

        enclosing = self._enclosing_stmt(tree, lineno)
        if enclosing is not None:
            return (
                f"Continuation of the {self._stmt_kind(enclosing)} that starts on "
                f"line {enclosing.lineno}: `{self._short(enclosing)}`."
            )
        return f"`{stripped}`."

    def line_concepts(self, source: str, lineno: int) -> list[str]:
        lines = source.splitlines()
        if lineno < 1 or lineno > len(lines):
            return []
        stripped = lines[lineno - 1].strip()
        if stripped.startswith("@"):
            return ["decorator", "definition-vs-execution"]
        if stripped.startswith(("try:", "except", "finally:")):
            return ["exceptions-and-flow", "block-and-indentation"]
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return []
        stmt = self._smallest_stmt_on_line(tree, lineno) or self._enclosing_stmt(tree, lineno)
        if stmt is None:
            return []
        slugs: list[str] = list(_LINE_CONCEPTS.get(type(stmt).__name__, []))
        # only look at expression nodes that actually sit on this line, so a
        # `class`/`def` header does not inherit concepts from its whole body
        for node in ast.walk(stmt):
            if getattr(node, "lineno", None) == lineno:
                slugs += _LINE_CONCEPTS_EXPR.get(type(node).__name__, [])
        seen: set[str] = set()
        ordered = []
        for s in slugs:
            if s not in seen:
                seen.add(s)
                ordered.append(s)
        return ordered[:4]

    # -- lexing --------------------------------------------------------

    def _lex(self, source: str) -> tuple[list[_Raw], str]:
        raw: list[_Raw] = []
        error = ""
        try:
            gen = tokenize.generate_tokens(io.StringIO(source).readline)
            for tok in gen:
                name = _token.tok_name[tok.type]
                if name in ("ENCODING", "ENDMARKER"):
                    continue
                norm = self._normalize_type(name, tok.string)
                raw.append(
                    _Raw(
                        type=norm,
                        raw_type=name,
                        string=tok.string,
                        start=tok.start,
                        end=tok.end,
                        line=tok.line,
                    )
                )
        except (tokenize.TokenError, IndentationError) as exc:
            error = f"tokenize stopped early: {exc}"
        return raw, error

    @staticmethod
    def _normalize_type(name: str, text: str) -> str:
        if name == "NAME":
            return "KEYWORD" if keyword.iskeyword(text) else "NAME"
        if name.startswith("FSTRING"):
            return "STRING"
        if name in ("OP", "NUMBER", "STRING", "COMMENT", "NEWLINE", "NL", "INDENT", "DEDENT"):
            return name
        if name in ("NAME", "KEYWORD"):
            return name
        return name

    # -- per-token lookup key ----------------------------------------

    def _key_for(
        self, r: _Raw, roles: dict[Pos, tuple[str, str]]
    ) -> tuple[str, str, str]:
        role, note = roles.get(r.start, ("", ""))
        t = r.type
        if t in ("OP", "KEYWORD"):
            return r.string, role, note
        if t == "STRING":
            return self._string_key(r)
        if t == "NUMBER":
            return self._number_key(r.string)
        if t == "COMMENT":
            return "#", "", ""
        if t in ("NEWLINE", "NL", "INDENT", "DEDENT"):
            return t, "", ""
        if t == "NAME":
            return "", role, note
        return "", role, note

    @staticmethod
    def _string_key(r: _Raw) -> tuple[str, str, str]:
        if r.raw_type == "FSTRING_START":
            return 'f"', "fstring", ""
        if r.raw_type == "FSTRING_MIDDLE":
            return 'f"', "fstring", "literal text inside an f-string"
        if r.raw_type == "FSTRING_END":
            return '"', "fstring", "the closing quote of the f-string"
        s = r.string
        i = 0
        while i < len(s) and s[i] not in "\"'":
            i += 1
        prefix = s[:i].lower()
        triple = s[i : i + 3] in ('"""', "'''")
        if "f" in prefix:
            return 'f"', "fstring", ""
        if "b" in prefix:
            return 'b"', "bytes", ""
        if "r" in prefix:
            return 'r"', "raw", ""
        if triple:
            return '"""', "triple", ""
        return '"', "plain", ""

    @staticmethod
    def _number_key(s: str) -> tuple[str, str, str]:
        low = s.lower()
        if low.startswith("0x"):
            return "0x", "hex", ""
        if low.startswith("0o"):
            return "0o", "octal", ""
        if low.startswith("0b"):
            return "0b", "binary", ""
        if low.endswith("j"):
            return "j", "imaginary", ""
        if "e" in low:
            return "e", "exponent", ""
        if "." in low:
            return "float", "float", ""
        if "_" in low:
            return "_", "digit-separator", ""
        return "int", "int", ""

    # -- role tagging -----------------------------------------------

    def _tag_roles(
        self,
        tree: ast.AST,
        raw: list[_Raw],
        roles: dict[Pos, tuple[str, str]],
    ) -> None:
        by_start = {r.start: i for i, r in enumerate(raw)}

        def put(pos: Pos, role: str, note: str = "") -> None:
            if pos is not None and pos not in roles:
                roles[pos] = (role, note)

        def first_op(after: Pos, ch: str, before: Pos | None = None) -> Pos | None:
            for r in raw:
                if r.start < after:
                    continue
                if before is not None and r.start >= before:
                    return None
                if r.type == "OP" and r.string == ch:
                    return r.start
            return None

        def last_op_before(before: Pos, ch: str, after: Pos) -> Pos | None:
            found = None
            for r in raw:
                if r.start < after:
                    continue
                if r.start >= before:
                    break
                if r.type == "OP" and r.string == ch:
                    found = r.start
            return found

        def first_kw(after: Pos, word: str, before: Pos | None = None) -> Pos | None:
            for r in raw:
                if r.start < after:
                    continue
                if before is not None and r.start >= before:
                    return None
                if r.type in ("KEYWORD", "NAME") and r.string == word:
                    return r.start
            return None

        def name_token(word: str, after: Pos, before: Pos) -> Pos | None:
            for r in raw:
                if r.start < after:
                    continue
                if r.start >= before:
                    return None
                if r.type in ("NAME", "KEYWORD") and r.string == word:
                    return r.start
            return None

        def endpos(node: ast.AST) -> Pos:
            return (node.end_lineno, node.end_col_offset)

        def startpos(node: ast.AST) -> Pos:
            return (node.lineno, node.col_offset)

        def close_of(open_pos: Pos, node: ast.AST, role: str) -> None:
            cpos = (node.end_lineno, node.end_col_offset - 1)
            idx = by_start.get(cpos)
            if idx is not None and raw[idx].type == "OP" and raw[idx].string in ")]}":
                put(cpos, role, "")

        def bracket_at_start(node: ast.AST, ch: str, role: str) -> None:
            pos = startpos(node)
            idx = by_start.get(pos)
            if idx is not None and raw[idx].string == ch:
                put(pos, role, "")
                close_of(pos, node, role)

        for node in ast.walk(tree):
            k = type(node).__name__

            if k in ("FunctionDef", "AsyncFunctionDef"):
                header_start = startpos(node)
                body_start = (node.body[0].lineno, 0) if node.body else (header_start[0] + 1, 0)
                name_pos = name_token(node.name, header_start, body_start)
                if name_pos:
                    put(name_pos, "definition", "the function's name")
                p_open = first_op(header_start, "(")
                if p_open:
                    put(p_open, "func-def-params", "")
                    end_paren = self._match_paren(raw, p_open)
                    if end_paren:
                        put(end_paren, "func-def-params", "")
                    if node.returns is not None and end_paren:
                        arrow = first_op(end_paren, "->", startpos(node.returns))
                        if arrow:
                            put(arrow, "return-annotation", "")
                if node.body:
                    bstart = startpos(node.body[0])
                    colon = last_op_before(bstart, ":", header_start)
                    if colon:
                        put(colon, "block", "")
                self._tag_arguments(node.args, raw, roles, first_op, last_op_before, put)

            elif k == "ClassDef":
                header_start = startpos(node)
                name_pos = name_token(node.name, header_start, (node.body[0].lineno, 0))
                if name_pos:
                    put(name_pos, "definition", "the class's name")
                if node.bases or node.keywords:
                    p_open = first_op(header_start, "(")
                    if p_open:
                        put(p_open, "class-bases", "")
                        end_paren = self._match_paren(raw, p_open)
                        if end_paren:
                            put(end_paren, "class-bases", "")
                if node.body:
                    colon = last_op_before(startpos(node.body[0]), ":", header_start)
                    if colon:
                        put(colon, "block", "")

            elif k in _BLOCK_NODES and getattr(node, "body", None):
                colon = last_op_before(startpos(node.body[0]), ":", startpos(node))
                if colon:
                    put(colon, "block", "")

            if k == "Call":
                fe = node.func
                open_pos = first_op(endpos(fe), "(", endpos(node))
                if open_pos:
                    put(open_pos, "call", "")
                    close_of(open_pos, node, "call")
                target = fe
                while isinstance(target, ast.Call):
                    target = target.func
                if isinstance(target, ast.Name):
                    put(startpos(target), "call", "the name being called")
                elif isinstance(target, ast.Attribute):
                    dpos = name_token(target.attr, startpos(target), endpos(target))
                    if dpos:
                        put(dpos, "call", "the method being called")

            elif k == "keyword":
                if node.arg is None:
                    dstar = first_op(startpos(node), "**", startpos(node.value))
                    if dstar:
                        put(dstar, "unpack", "spreads a dict in as keyword arguments")
                else:
                    eq = first_op(startpos(node), "=", startpos(node.value))
                    if eq:
                        put(eq, "kwarg", "")

            elif k == "Attribute":
                dot = first_op(endpos(node.value), ".", endpos(node))
                if dot:
                    put(dot, "attribute", "")
                apos = name_token(node.attr, endpos(node.value), endpos(node))
                if apos:
                    put(apos, "attribute", "the attribute name")

            elif k == "Subscript":
                ob = first_op(endpos(node.value), "[", endpos(node))
                if ob:
                    put(ob, "subscript", "")
                    end_b = self._match_paren(raw, ob)
                    if end_b:
                        put(end_b, "subscript", "")
                    for r in raw:
                        if ob < r.start < endpos(node) and r.type == "OP" and r.string == ":":
                            put(r.start, "slice", "")

            elif k == "BinOp":
                ch, role = _BINOP[type(node.op).__name__]
                pos = first_op(endpos(node.left), ch, startpos(node.right))
                if pos:
                    put(pos, role, "")

            elif k == "UnaryOp" and type(node.op).__name__ in _UNARY:
                ch, role = _UNARY[type(node.op).__name__]
                pos = first_op(startpos(node), ch, startpos(node.operand))
                if pos:
                    put(pos, role, "")

            elif k == "Compare":
                prev_end = endpos(node.left)
                for op, comp in zip(node.ops, node.comparators):
                    ch, role = _CMP[type(op).__name__]
                    if ch in ("is", "in"):
                        pos = first_kw(prev_end, ch, startpos(comp))
                    else:
                        pos = first_op(prev_end, ch, startpos(comp))
                    if pos:
                        put(pos, role, "")
                    prev_end = endpos(comp)

            elif k == "Assign":
                pos = first_op(endpos(node.targets[-1]), "=", startpos(node.value))
                if pos:
                    put(pos, "assign", "")

            elif k == "AugAssign":
                ch = _BINOP.get(type(node.op).__name__, ("", ""))[0] + "="
                pos = first_op(endpos(node.target), ch, startpos(node.value))
                if pos:
                    put(pos, "aug-assign", "")

            elif k == "AnnAssign":
                cpos = first_op(endpos(node.target), ":", startpos(node.annotation))
                if cpos:
                    put(cpos, "annotation", "")
                if node.value is not None:
                    epos = first_op(endpos(node.annotation), "=", startpos(node.value))
                    if epos:
                        put(epos, "annotated-assign", "")

            elif k == "Starred":
                pos = by_start.get(startpos(node))
                if pos is not None and raw[pos].string == "*":
                    put(startpos(node), "unpack", "")

            elif k == "Dict":
                bracket_at_start(node, "{", "dict")
                for key, val in zip(node.keys, node.values):
                    if key is None:
                        dstar = first_op(
                            (val.lineno, max(0, val.col_offset - 3)), "**", startpos(val)
                        )
                        if dstar:
                            put(dstar, "unpack", "merges another dict's items in")
                    else:
                        cpos = first_op(endpos(key), ":", startpos(val))
                        if cpos:
                            put(cpos, "dict-pair", "")

            elif k == "Set":
                bracket_at_start(node, "{", "set")
            elif k == "DictComp":
                bracket_at_start(node, "{", "dict-comp")
                cpos = first_op(endpos(node.key), ":", startpos(node.value))
                if cpos:
                    put(cpos, "dict-pair", "")
            elif k == "SetComp":
                bracket_at_start(node, "{", "set-comp")
            elif k == "Lambda":
                cpos = first_op(startpos(node), ":", startpos(node.body))
                if cpos:
                    put(cpos, "lambda", "")
            elif k == "List":
                bracket_at_start(node, "[", "list")
            elif k == "ListComp":
                bracket_at_start(node, "[", "list-comp")
            elif k == "Tuple":
                bracket_at_start(node, "(", "tuple")
            elif k == "GeneratorExp":
                bracket_at_start(node, "(", "generator")

            elif k == "IfExp":
                ipos = first_kw(endpos(node.body), "if", startpos(node.test))
                if ipos:
                    put(ipos, "ternary", "")
                epos = first_kw(endpos(node.test), "else", startpos(node.orelse))
                if epos:
                    put(epos, "ternary", "")

            elif k == "If" and not self._is_elif(raw, node):
                pos = by_start.get(startpos(node))
                if pos is not None and raw[pos].string == "if":
                    put(startpos(node), "statement", "")

            if k in ("ListComp", "SetComp", "DictComp", "GeneratorExp"):
                for comp in node.generators:
                    inpos = first_kw(endpos(comp.target), "in", startpos(comp.iter))
                    if inpos:
                        put(inpos, "for-clause", "")
                    for cond in comp.ifs:
                        ipos = last_op_before  # noqa: F841 (kept for symmetry)
                        cand = name_token("if", startpos(node), startpos(cond))
                        # take the closest 'if' before the condition
                        closest = None
                        for r in raw:
                            if r.type in ("KEYWORD", "NAME") and r.string == "if" and startpos(node) <= r.start < startpos(cond):
                                closest = r.start
                        if closest:
                            put(closest, "comp-filter", "")

            if k in ("For", "AsyncFor"):
                inpos = first_kw(endpos(node.target), "in", startpos(node.iter))
                if inpos:
                    put(inpos, "for-clause", "")

    def _tag_arguments(self, args, raw, roles, first_op, last_op_before, put) -> None:
        for a in list(args.posonlyargs) + list(args.args) + list(args.kwonlyargs):
            put((a.lineno, a.col_offset), "parameter", "")
        if args.vararg:
            v = args.vararg
            star = last_op_before((v.lineno, v.col_offset), "*", (v.lineno - 1, 0))
            if star:
                put(star, "var-positional", "")
            put((v.lineno, v.col_offset), "parameter", "")
        if args.kwarg:
            kw = args.kwarg
            dstar = last_op_before((kw.lineno, kw.col_offset), "**", (kw.lineno - 1, 0))
            if dstar:
                put(dstar, "var-keyword", "")
            put((kw.lineno, kw.col_offset), "parameter", "")
        if args.kwonlyargs and not args.vararg:
            first_kwonly = args.kwonlyargs[0]
            star = last_op_before(
                (first_kwonly.lineno, first_kwonly.col_offset), "*", (first_kwonly.lineno - 1, 0)
            )
            if star:
                put(star, "kwonly-marker", "")
        for a, d in self._align_defaults(args):
            if d is None:
                continue
            eq = first_op((a.end_lineno, a.end_col_offset), "=", (d.lineno, d.col_offset))
            if eq:
                put(eq, "param-default", "")

    @staticmethod
    def _align_defaults(args):
        pairs = []
        positional = list(args.posonlyargs) + list(args.args)
        defaults = list(args.defaults)
        if defaults:
            for a, d in zip(positional[-len(defaults):], defaults):
                pairs.append((a, d))
        for a, d in zip(args.kwonlyargs, args.kw_defaults):
            pairs.append((a, d))
        return pairs

    @staticmethod
    def _match_paren(raw: list[_Raw], open_pos: Pos) -> Pos | None:
        pairs = {"(": ")", "[": "]", "{": "}"}
        opener = None
        for r in raw:
            if r.start == open_pos:
                opener = r.string
                break
        if opener not in pairs:
            return None
        closer = pairs[opener]
        depth = 0
        started = False
        for r in raw:
            if r.start < open_pos:
                continue
            if r.type != "OP":
                continue
            if r.string == opener:
                depth += 1
                started = True
            elif r.string == closer:
                depth -= 1
                if started and depth == 0:
                    return r.start
        return None

    @staticmethod
    def _is_elif(raw: list[_Raw], node: ast.If) -> bool:
        for r in raw:
            if r.start == (node.lineno, node.col_offset):
                return r.string == "elif"
        return False

    def _tag_fstring_fields(self, raw, roles) -> None:
        depth = 0
        for r in raw:
            if r.raw_type == "FSTRING_START":
                depth += 1
            elif r.raw_type == "FSTRING_END":
                depth = max(0, depth - 1)
            elif depth > 0 and r.type == "OP" and r.string in "{}":
                roles.setdefault(r.start, ("fstring-field", ""))

    def _tag_decorators(self, raw, roles) -> None:
        line_first: dict[int, Pos] = {}
        for r in raw:
            if r.type in ("INDENT", "DEDENT", "NL", "NEWLINE", "COMMENT"):
                continue
            line_first.setdefault(r.start[0], r.start)
        for r in raw:
            if r.type == "OP" and r.string == "@" and r.start not in roles:
                if line_first.get(r.start[0]) == r.start:
                    roles[r.start] = ("decorator", "")
                else:
                    roles[r.start] = ("matmul", "")

    # -- line description ------------------------------------------

    def _smallest_stmt_on_line(self, tree: ast.AST, lineno: int) -> ast.stmt | None:
        best: ast.stmt | None = None
        for node in ast.walk(tree):
            if isinstance(node, ast.stmt) and getattr(node, "lineno", None) == lineno:
                span = (node.end_lineno or node.lineno) - node.lineno
                if best is None or span < ((best.end_lineno or best.lineno) - best.lineno):
                    best = node
        return best

    def _enclosing_stmt(self, tree: ast.AST, lineno: int) -> ast.stmt | None:
        best: ast.stmt | None = None
        for node in ast.walk(tree):
            if isinstance(node, ast.stmt):
                lo, hi = node.lineno, (node.end_lineno or node.lineno)
                if lo <= lineno <= hi:
                    span = hi - lo
                    if best is None or span < ((best.end_lineno or best.lineno) - best.lineno):
                        best = node
        return best

    def _stmt_kind(self, node: ast.stmt) -> str:
        return {
            "FunctionDef": "function definition",
            "AsyncFunctionDef": "async function definition",
            "ClassDef": "class definition",
            "Assign": "assignment",
            "AnnAssign": "annotated assignment",
            "AugAssign": "augmented assignment",
            "Expr": "expression statement",
            "Return": "return statement",
            "If": "if statement",
            "For": "for loop",
            "While": "while loop",
            "With": "with statement",
            "Try": "try statement",
            "Import": "import",
            "ImportFrom": "import",
            "Raise": "raise statement",
            "Assert": "assert statement",
        }.get(type(node).__name__, "statement")

    def _short(self, node: ast.AST, limit: int = 90) -> str:
        try:
            text = ast.unparse(node)
        except Exception:
            return "..."
        text = " ".join(text.split())
        return text if len(text) <= limit else text[: limit - 1] + "…"

    def _expr(self, node: ast.AST | None, depth: int = 0) -> str:
        if node is None:
            return "nothing"
        k = type(node).__name__
        if k == "Constant":
            v = node.value
            if v is None or isinstance(v, bool):
                return f"`{v!r}`"
            if isinstance(v, str):
                short = v if len(v) <= 24 else v[:23] + "…"
                return f'the text `"{short}"`'
            return f"the value `{v!r}`"
        if k == "Name":
            return f"the variable `{node.id}`"
        if k == "Attribute":
            return f"`{self._short(node)}`"
        if k == "Call":
            fn = self._short(node.func)
            if depth == 0:
                n = len(node.args) + len(node.keywords)
                if n == 0:
                    return f"the result of calling `{fn}()`"
                return f"the result of calling `{fn}` with {n} argument{'s' if n != 1 else ''}"
            return f"`{fn}(…)`"
        if k == "BinOp" and depth < 2:
            word = _BINOP_WORD.get(type(node.op).__name__, "combined with")
            return f"{self._expr(node.left, depth + 1)} {word} {self._expr(node.right, depth + 1)}"
        if k == "Compare" and depth < 2:
            parts = [self._expr(node.left, depth + 1)]
            for op, comp in zip(node.ops, node.comparators):
                parts.append(_CMP_WORD.get(type(op).__name__, "compared with"))
                parts.append(self._expr(comp, depth + 1))
            return " ".join(parts)
        if k == "BoolOp" and depth < 2:
            joiner = " and " if type(node.op).__name__ == "And" else " or "
            return joiner.join(self._expr(v, depth + 1) for v in node.values)
        if k == "UnaryOp":
            opname = type(node.op).__name__
            if opname == "Not":
                return f"not {self._expr(node.operand, depth + 1)}"
            if opname == "USub":
                return f"the negative of {self._expr(node.operand, depth + 1)}"
        if k in ("List", "Tuple", "Set"):
            return f"a {k.lower()} of {len(node.elts)} item{'s' if len(node.elts) != 1 else ''}"
        if k == "Dict":
            return f"a dict of {len(node.keys)} pair{'s' if len(node.keys) != 1 else ''}"
        if k == "Subscript":
            return f"`{self._short(node)}`"
        if k == "IfExp":
            return (
                f"{self._expr(node.body, depth + 1)} if {self._expr(node.test, depth + 1)} "
                f"otherwise {self._expr(node.orelse, depth + 1)}"
            )
        if k in ("ListComp", "SetComp", "DictComp", "GeneratorExp"):
            return f"`{self._short(node)}`"
        return f"`{self._short(node)}`"

    def _describe_stmt(self, node: ast.stmt) -> str:
        k = type(node).__name__
        handler = getattr(self, f"_d_{k.lower()}", None)
        if handler is not None:
            return handler(node)
        return f"Runs the statement `{self._short(node)}`."

    # individual statement templates -------------------------------

    def _targets(self, targets) -> str:
        names = [self._short(t) for t in targets]
        return ", ".join(f"`{n}`" for n in names)

    def _d_assign(self, node: ast.Assign) -> str:
        tgt = self._targets(node.targets)
        if isinstance(node.value, ast.Call):
            return f"Calls `{self._short(node.value.func)}` and stores the result in {tgt}."
        return f"Assigns {self._expr(node.value)} to {tgt}."

    def _d_annassign(self, node: ast.AnnAssign) -> str:
        target = f"`{self._short(node.target)}`"
        ann = f"`{self._short(node.annotation)}`"
        if node.value is not None:
            return f"Declares {target} as type {ann} and assigns {self._expr(node.value)}."
        return f"Declares that {target} has type {ann} (no value assigned here)."

    def _d_augassign(self, node: ast.AugAssign) -> str:
        word = _BINOP_WORD.get(type(node.op).__name__, "combined with")
        return f"Updates `{self._short(node.target)}` in place: {word} {self._expr(node.value)}."

    def _d_expr(self, node: ast.Expr) -> str:
        v = node.value
        if isinstance(v, ast.Call):
            n = len(v.args) + len(v.keywords)
            if n == 0:
                return f"Calls `{self._short(v.func)}()` with no arguments."
            args = ", ".join(f"`{self._short(a)}`" for a in v.args)
            kw = ", ".join(f"`{k.arg}=…`" for k in v.keywords if k.arg)
            joined = ", ".join(p for p in (args, kw) if p)
            return f"Calls `{self._short(v.func)}` with {joined}."
        if isinstance(v, ast.Constant) and isinstance(v.value, str):
            return "A bare string literal — used here as a docstring/comment; it has no runtime effect."
        if isinstance(v, (ast.Yield, ast.YieldFrom)):
            return "Yields a value from this generator, pausing until the next value is requested."
        if isinstance(v, ast.Await):
            return f"Awaits {self._expr(v.value)}, letting the event loop run other tasks meanwhile."
        return f"Evaluates `{self._short(v)}` and discards the result."

    def _d_return(self, node: ast.Return) -> str:
        if node.value is None:
            return "Returns `None`, ending the current function."
        return f"Returns {self._expr(node.value)} from the current function."

    def _d_if(self, node: ast.If) -> str:
        return f"If {self._expr(node.test)}, run the indented block below; otherwise skip to any elif/else."

    def _d_while(self, node: ast.While) -> str:
        return f"Keep repeating the indented block while {self._expr(node.test)}."

    def _d_for(self, node: ast.For) -> str:
        return (
            f"For each item in {self._expr(node.iter)}, bind it to `{self._short(node.target)}` "
            f"and run the indented block."
        )

    def _d_asyncfor(self, node: ast.AsyncFor) -> str:
        return f"Async-iterates {self._expr(node.iter)}, binding each item to `{self._short(node.target)}`."

    def _d_functiondef(self, node: ast.FunctionDef) -> str:
        params = ", ".join(a.arg for a in node.args.args) or "no parameters"
        ret = f" -> `{self._short(node.returns)}`" if node.returns is not None else ""
        deco = ""
        if node.decorator_list:
            deco = " (wrapped by " + ", ".join(f"`@{self._short(d)}`" for d in node.decorator_list) + ")"
        return f"Defines a function `{node.name}` taking {params}{ret}{deco}. The body runs only when it is called."

    def _d_asyncfunctiondef(self, node: ast.AsyncFunctionDef) -> str:
        params = ", ".join(a.arg for a in node.args.args) or "no parameters"
        return f"Defines an async coroutine `{node.name}` taking {params}; calling it returns a coroutine to await."

    def _d_classdef(self, node: ast.ClassDef) -> str:
        if node.bases:
            bases = ", ".join(f"`{self._short(b)}`" for b in node.bases)
            return f"Defines a class `{node.name}` that inherits from {bases}."
        return f"Defines a class `{node.name}` (inherits only from `object`)."

    def _d_import(self, node: ast.Import) -> str:
        mods = ", ".join(
            f"`{a.name}`" + (f" as `{a.asname}`" if a.asname else "") for a in node.names
        )
        return f"Imports the module(s) {mods}."

    def _d_importfrom(self, node: ast.ImportFrom) -> str:
        mod = "." * node.level + (node.module or "")
        names = ", ".join(
            f"`{a.name}`" + (f" as `{a.asname}`" if a.asname else "") for a in node.names
        )
        return f"From `{mod}`, imports {names} into this module's namespace."

    def _d_with(self, node: ast.With) -> str:
        items = ", ".join(f"`{self._short(i.context_expr)}`" for i in node.items)
        return f"Runs the block below with {items} as a managed context that is cleaned up on exit."

    def _d_raise(self, node: ast.Raise) -> str:
        if node.exc is None:
            return "Re-raises the exception currently being handled."
        return f"Raises `{self._short(node.exc)}`, unwinding until something catches it."

    def _d_assert(self, node: ast.Assert) -> str:
        return f"Checks that {self._expr(node.test)}; raises AssertionError if not."

    def _d_pass(self, node: ast.Pass) -> str:
        return "Does nothing — a placeholder where a statement is syntactically required."

    def _d_break(self, node: ast.Break) -> str:
        return "Exits the innermost loop immediately."

    def _d_continue(self, node: ast.Continue) -> str:
        return "Skips to the next iteration of the innermost loop."

    def _d_global(self, node: ast.Global) -> str:
        return f"Declares {', '.join(f'`{n}`' for n in node.names)} as module-level, so assignments here update the global."

    def _d_nonlocal(self, node: ast.Nonlocal) -> str:
        return f"Binds {', '.join(f'`{n}`' for n in node.names)} to the nearest enclosing function's variable."

    def _d_delete(self, node: ast.Delete) -> str:
        return f"Deletes {self._targets(node.targets)}."

    def _d_try(self, node: ast.Try) -> str:
        return "Begins a try block; exceptions raised inside are matched against the except clause(s) below."


_BARE_HEADERS = {
    "else:": "The fallback block, run when the conditions above were all false (or, after a loop, when it finished without break).",
    "try:": "Begins a try block; exceptions raised inside are handled by the except clause(s) below.",
    "finally:": "Cleanup block that always runs when leaving the try above — normally, via exception, or via return.",
}


# --------------------------------------------------------------------------
# token -> background-concept slugs
# --------------------------------------------------------------------------

# keyed by role (checked first), then by lexeme, then by token type
_CONCEPTS_BY_ROLE = {
    "call": ["function-call", "argument-vs-parameter"],
    "func-def-params": ["argument-vs-parameter", "definition-vs-execution"],
    "class-bases": ["definition-vs-execution"],
    "tuple": ["collection-literals"],
    "generator": ["comprehension", "iteration-and-iterables"],
    "group": ["operator-and-operand", "expression-vs-statement"],
    "list": ["collection-literals"],
    "set": ["collection-literals"],
    "dict": ["collection-literals"],
    "subscript": ["collection-literals", "attribute-access"],
    "list-comp": ["comprehension", "iteration-and-iterables"],
    "dict-comp": ["comprehension", "iteration-and-iterables"],
    "set-comp": ["comprehension", "iteration-and-iterables"],
    "fstring-field": ["string-literals", "expression-vs-statement"],
    "attribute": ["attribute-access"],
    "assign": ["binding"],
    "annotated-assign": ["binding"],
    "annotation": ["binding"],
    "kwarg": ["argument-vs-parameter"],
    "param-default": ["argument-vs-parameter"],
    "aug-assign": ["binding", "mutability", "operator-and-operand"],
    "block": ["block-and-indentation"],
    "slice": ["collection-literals"],
    "dict-pair": ["collection-literals"],
    "arithmetic": ["operator-and-operand"],
    "bitwise": ["operator-and-operand"],
    "unary": ["operator-and-operand"],
    "comparison": ["comparison-and-chaining", "operator-and-operand"],
    "matmul": ["operator-and-operand"],
    "membership": ["operator-and-operand", "iteration-and-iterables"],
    "for-clause": ["iteration-and-iterables", "block-and-indentation"],
    "ternary": ["expression-vs-statement", "truthiness"],
    "statement": ["truthiness", "block-and-indentation"],
    "comp-filter": ["comprehension", "truthiness"],
    "decorator": ["decorator"],
    "return-annotation": ["binding", "definition-vs-execution"],
    "unpack": ["argument-vs-parameter", "collection-literals"],
    "var-positional": ["argument-vs-parameter"],
    "var-keyword": ["argument-vs-parameter"],
    "kwonly-marker": ["argument-vs-parameter"],
    "definition": ["definition-vs-execution"],
    "parameter": ["argument-vs-parameter"],
}

_CONCEPTS_BY_LEXEME = {
    "and": ["truthiness", "operator-and-operand"],
    "or": ["truthiness", "operator-and-operand"],
    "not": ["truthiness", "operator-and-operand"],
    "is": ["none-and-absence", "comparison-and-chaining"],
    "if": ["truthiness", "block-and-indentation"],
    "elif": ["truthiness", "block-and-indentation"],
    "else": ["truthiness", "block-and-indentation"],
    "for": ["iteration-and-iterables", "block-and-indentation"],
    "while": ["iteration-and-iterables", "truthiness", "block-and-indentation"],
    "def": ["definition-vs-execution", "argument-vs-parameter", "block-and-indentation"],
    "class": ["definition-vs-execution", "block-and-indentation"],
    "lambda": ["function-call", "definition-vs-execution"],
    "return": ["function-call"],
    "yield": ["function-call", "iteration-and-iterables"],
    "import": ["scope-and-namespaces"],
    "from": ["scope-and-namespaces"],
    "global": ["scope-and-namespaces"],
    "nonlocal": ["scope-and-namespaces"],
    "try": ["exceptions-and-flow", "block-and-indentation"],
    "except": ["exceptions-and-flow"],
    "finally": ["exceptions-and-flow"],
    "raise": ["exceptions-and-flow"],
    "assert": ["exceptions-and-flow"],
    "with": ["block-and-indentation", "exceptions-and-flow"],
    "None": ["none-and-absence"],
    "True": ["truthiness"],
    "False": ["truthiness"],
    ":=": ["binding", "expression-vs-statement"],
    "=": ["binding"],
    ".": ["attribute-access"],
    "#": ["comment-and-docstring"],
    '"""': ["string-literals", "comment-and-docstring"],
}

_CONCEPTS_BY_TYPE = {
    "STRING": ["string-literals"],
    "COMMENT": ["comment-and-docstring"],
    "INDENT": ["block-and-indentation"],
    "DEDENT": ["block-and-indentation"],
}


def _concepts_for(lexeme: str, ttype: str, role: str) -> list[str]:
    slugs: list[str] = []
    slugs += _CONCEPTS_BY_ROLE.get(role, [])
    slugs += _CONCEPTS_BY_LEXEME.get(lexeme, [])
    if not slugs:
        slugs += _CONCEPTS_BY_TYPE.get(ttype, [])
    seen: set[str] = set()
    ordered = []
    for s in slugs:
        if s not in seen:
            seen.add(s)
            ordered.append(s)
    return ordered


_LINE_CONCEPTS = {
    "Assign": ["binding"],
    "AnnAssign": ["binding"],
    "AugAssign": ["binding", "mutability"],
    "FunctionDef": ["definition-vs-execution", "argument-vs-parameter", "block-and-indentation"],
    "AsyncFunctionDef": ["definition-vs-execution", "argument-vs-parameter", "block-and-indentation"],
    "ClassDef": ["definition-vs-execution", "block-and-indentation"],
    "Return": ["function-call"],
    "If": ["truthiness", "block-and-indentation"],
    "For": ["iteration-and-iterables", "block-and-indentation"],
    "AsyncFor": ["iteration-and-iterables", "block-and-indentation"],
    "While": ["iteration-and-iterables", "truthiness", "block-and-indentation"],
    "With": ["block-and-indentation", "exceptions-and-flow"],
    "AsyncWith": ["block-and-indentation", "exceptions-and-flow"],
    "Try": ["exceptions-and-flow", "block-and-indentation"],
    "Raise": ["exceptions-and-flow"],
    "Assert": ["exceptions-and-flow"],
    "Import": ["scope-and-namespaces"],
    "ImportFrom": ["scope-and-namespaces"],
    "Global": ["scope-and-namespaces"],
    "Nonlocal": ["scope-and-namespaces"],
}

_LINE_CONCEPTS_EXPR = {
    "Call": ["function-call", "argument-vs-parameter"],
    "ListComp": ["comprehension", "iteration-and-iterables"],
    "SetComp": ["comprehension", "iteration-and-iterables"],
    "DictComp": ["comprehension", "iteration-and-iterables"],
    "GeneratorExp": ["comprehension", "iteration-and-iterables"],
    "Lambda": ["function-call", "definition-vs-execution"],
    "BoolOp": ["truthiness", "operator-and-operand"],
    "Compare": ["comparison-and-chaining"],
    "BinOp": ["operator-and-operand"],
    "Attribute": ["attribute-access"],
    "ListLit": ["collection-literals"],
}

# Bundled standard-library member data (trust tier 2), loaded once on first use.
_STDLIB_DATA: dict[str, dict[str, str]] | None = None


def _stdlib_data() -> dict[str, dict[str, str]]:
    global _STDLIB_DATA
    if _STDLIB_DATA is None:
        try:
            text = (
                _res_files("codecrawler.seeds")
                .joinpath("python_stdlib.json")
                .read_text(encoding="utf-8")
            )
            loaded = json.loads(text)
            _STDLIB_DATA = loaded if isinstance(loaded, dict) else {}
        except (OSError, ValueError, ModuleNotFoundError):
            _STDLIB_DATA = {}
    return _STDLIB_DATA

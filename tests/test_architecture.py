"""Static architecture rules (ARCHITECTURE.md §3, §11). Stdlib only, no extra tooling."""

from __future__ import annotations

import ast
import importlib
import pkgutil
from pathlib import Path

import dealradar

PKG_ROOT = Path(dealradar.__file__).resolve().parent
CATEGORIES = ("tech", "apparel", "food", "home")


def _modules() -> dict[str, Path]:
    found: dict[str, Path] = {}
    for path in PKG_ROOT.rglob("*.py"):
        rel = path.relative_to(PKG_ROOT.parent).with_suffix("")
        parts = list(rel.parts)
        if "versions" in parts:  # alembic revision files are not importable modules
            continue
        if parts[-1] == "__init__":
            parts = parts[:-1]
        found[".".join(parts)] = path
    return found


MODULES = _modules()


def _imports(path: Path, module: str) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    is_pkg = path.name == "__init__.py"
    result: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = module.split(".")
                base = base if is_pkg else base[:-1]
                base = base[: len(base) - (node.level - 1)]
                prefix = ".".join(base)
                target = f"{prefix}.{node.module}" if node.module else prefix
            else:
                target = node.module or ""
            result.add(target)
            # "from pkg import submodule" also depends on the submodule
            for alias in node.names:
                candidate = f"{target}.{alias.name}"
                if candidate in MODULES:
                    result.add(candidate)
    return {i for i in result if i == "dealradar" or i.startswith("dealradar.")}


GRAPH = {m: _imports(p, m) for m, p in MODULES.items()}


def _violations(prefix: str, allowed: tuple[str, ...]) -> list[str]:
    bad = []
    for mod, deps in GRAPH.items():
        if mod != prefix and not mod.startswith(prefix + "."):
            continue
        for dep in deps:
            if dep == "dealradar" or dep.startswith(prefix):
                continue
            if not any(dep == a or dep.startswith(a + ".") for a in allowed):
                bad.append(f"{mod} -> {dep}")
    return bad


def test_every_module_imports() -> None:
    for name, _ in sorted(MODULES.items()):
        if name.endswith("migrations.env") or name.startswith("dealradar.ui.page_scripts."):
            continue  # executed by alembic / st.navigation, not importable modules
        importlib.import_module(name)


def test_no_import_cycles() -> None:
    visiting: set[str] = set()
    done: set[str] = set()
    cycles: list[list[str]] = []

    def visit(node: str, stack: list[str]) -> None:
        if node in done:
            return
        if node in visiting:
            cycles.append([*stack[stack.index(node) :], node])
            return
        visiting.add(node)
        for dep in GRAPH.get(node, ()):
            if dep in GRAPH and dep != node and not node.startswith(dep + "."):
                visit(dep, [*stack, node])
        visiting.discard(node)
        done.add(node)

    for mod in GRAPH:
        visit(mod, [])
    assert not cycles, cycles


def test_core_depends_on_nothing() -> None:
    assert _violations("dealradar.core", ()) == []


def test_db_depends_only_on_core() -> None:
    assert _violations("dealradar.db", ("dealradar.core",)) == []


SHARED_DOMAIN = (
    "dealradar.core",
    "dealradar.normalize",
    "dealradar.matching",
    "dealradar.evaluation",
    "dealradar.pricing",
)


def test_categories_independent() -> None:
    """A category may use the shared domain layers and categories.base - never another category."""
    for cat in CATEGORIES:
        prefix = f"dealradar.categories.{cat}"
        allowed = (*SHARED_DOMAIN, "dealradar.categories.base")
        assert _violations(prefix, allowed) == [], cat
    assert _violations("dealradar.categories.base", SHARED_DOMAIN) == []


def test_shared_domain_layers_know_no_categories_or_db() -> None:
    assert _violations("dealradar.normalize", ("dealradar.core",)) == []
    assert _violations("dealradar.matching", ("dealradar.core", "dealradar.normalize")) == []
    assert _violations("dealradar.evaluation", ("dealradar.core", "dealradar.normalize")) == []
    assert _violations("dealradar.pricing", ("dealradar.core",)) == []  # pure engine


def test_category_modules_satisfy_protocol() -> None:
    from dealradar.categories.registry import module_for
    from dealradar.core.enums import Category

    required = (
        "normalize",
        "validate",
        "identifier_requires_brand",
        "identifier_pins_variant",
        "rule_key",
        "product_rule_key",
        "contradictions",
        "evaluation_inputs",
        "product_attrs_model",
        "variant_attrs_model",
        "listing_attrs_model",
        "fuzzy_threshold",
        "rule_key_decisive",
        "info",
        "benchmark_policy",
    )
    for category in Category:
        module = module_for(category)
        missing = [name for name in required if not hasattr(module, name)]
        assert missing == [], (category, missing)
        assert module.info.key is category


def test_ui_uses_services_and_core_only() -> None:
    assert _violations("dealradar.ui", ("dealradar.services", "dealradar.core")) == []


def test_services_never_import_ui() -> None:
    bad = [
        f"{m} -> {d}"
        for m, deps in GRAPH.items()
        if m.startswith("dealradar.services")
        for d in deps
        if d.startswith("dealradar.ui")
    ]
    assert bad == []


def test_no_category_branching_outside_categories() -> None:
    offenders = []
    for mod, path in MODULES.items():
        if mod.startswith("dealradar.categories") or mod.startswith("dealradar.core"):
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Compare):
                names = {ast.unparse(n) for n in [node.left, *node.comparators]}
                if any(n.startswith("Category.") for n in names):
                    offenders.append(f"{mod}:{node.lineno}")
    assert offenders == []


def test_no_float_in_money_module() -> None:
    tree = ast.parse((PKG_ROOT / "core" / "money.py").read_text(encoding="utf-8"))
    floats = [
        n.lineno
        for n in ast.walk(tree)
        if (isinstance(n, ast.Constant) and isinstance(n.value, float))
        or (isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "float")
    ]
    assert floats == []


def test_engines_are_independent_and_pure() -> None:
    """ADR-002/003: engines see only core + evaluation; never each other, categories, db,
    pricing or services."""
    allowed = ("dealradar.core", "dealradar.evaluation")
    assert _violations("dealradar.engines.personal", allowed) == []
    assert _violations("dealradar.engines.resale", allowed) == []


def test_no_combined_score_anywhere() -> None:
    """No module may build anything from both engines' verdicts except the service that runs
    them separately; the result types share no score field."""
    from dealradar.engines.personal import PersonalResult
    from dealradar.engines.resale import ResaleResult

    shared = set(PersonalResult.__dataclass_fields__) & set(ResaleResult.__dataclass_fields__)
    assert shared <= {
        "verdict",
        "reasons",
        "missing_inputs",
        "review_flags",
        "assumptions",
        "engine",
        "decision_required",
    }
    users = [
        m
        for m, deps in GRAPH.items()
        if "dealradar.engines.personal" in deps and "dealradar.engines.resale" in deps
    ]
    # services.evaluation runs them separately; services.analysis lists both verdicts as separate
    # lines in the Claude package. Neither combines them into a score.
    assert set(users) <= {
        "dealradar.engines",
        "dealradar.services.evaluation",
        "dealradar.services.analysis",
        "dealradar.services.workflow",  # stores both results in separate tables / lists
    }


def test_claude_bridge_is_pure_and_cannot_change_decisions() -> None:
    """ADR-011/048: the bridge sees only core + normalize - never engines, pricing, db, services -
    so a pasted answer has no code path to prices, matches, benchmarks or verdicts."""
    assert _violations("dealradar.claude_bridge", ("dealradar.core", "dealradar.normalize")) == []
    from dealradar.claude_bridge.schema import AnalysisResponse, Recommendation

    assert "BUY" not in {r.value for r in Recommendation}
    numeric = [n for n, f in AnalysisResponse.model_fields.items() if f.annotation in (int, float)]
    assert numeric == []  # no price / profit / score fields an answer could inject


def test_ledger_calculations_are_pure() -> None:
    """Realized profit is computed from recorded transactions only - no engine estimates."""
    assert _violations("dealradar.ledger", ("dealradar.core",)) == []


def test_source_adapters_cannot_reach_db_engines_or_services() -> None:
    allowed = ("dealradar.core", "dealradar.normalize", "dealradar.sources")
    assert _violations("dealradar.sources", allowed) == []


def test_telegram_is_optional_stdlib_only() -> None:
    """No third-party Telegram client; nothing outside notify talks to Telegram."""
    offenders = []
    for mod, path in MODULES.items():
        text = path.read_text(encoding="utf-8")
        if "api.telegram.org" in text and mod != "dealradar.services.notify":
            offenders.append(mod)
        if "import telegram" in text or "from telegram" in text:
            offenders.append(mod)
    assert offenders == []


def test_no_purchase_code_paths() -> None:
    """Nothing in the package places orders, fills carts or automates a browser."""
    forbidden = ("playwright", "selenium", "webbrowser", "add_to_cart", "checkout", "anthropic")
    offenders = []
    for mod, path in MODULES.items():
        text = path.read_text(encoding="utf-8").lower()
        offenders += [
            f"{mod}: {word}" for word in forbidden if f"import {word}" in text or f"{word}(" in text
        ]
    assert offenders == []


def test_no_invisible_or_bidi_characters_in_source() -> None:
    """'Trojan Source' guard: control, zero-width and bidi characters must be written as
    escapes (e.g. "\\u202e"), never literally, so code reads the way it executes."""
    import unicodedata

    root = PKG_ROOT.parent
    offenders = []
    for path in [*PKG_ROOT.rglob("*.py"), *(root / "tests").rglob("*.py")]:
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for ch in line:
                if unicodedata.category(ch) in ("Cf", "Cc") and ch != "\t":
                    offenders.append(f"{path.name}:{lineno} U+{ord(ch):04X}")
    assert offenders == []


def test_ui_pages_exist_for_navigation() -> None:
    app = (PKG_ROOT / "ui" / "app.py").read_text(encoding="utf-8")
    pages = (
        "overview",
        *CATEGORIES,
        "offer",
        "watchlists",
        "inventory",
        "feedback",
        "analysis",
        "settings",
        "sources",
        "health",
    )
    for page in pages:
        assert f'"page_scripts/{page}.py"' in app
        assert (PKG_ROOT / "ui" / "page_scripts" / f"{page}.py").exists()
    # A folder named "pages" next to app.py hijacks st.navigation (legacy multipage mode).
    assert not (PKG_ROOT / "ui" / "pages").exists()


def test_every_category_registered() -> None:
    from dealradar.categories.registry import all_categories
    from dealradar.core.enums import Category

    assert [c.key for c in all_categories()] == list(Category)
    assert {m.name for m in pkgutil.iter_modules([str(PKG_ROOT / "categories")]) if m.ispkg} == set(
        CATEGORIES
    )

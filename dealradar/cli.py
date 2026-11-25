"""Command-line entry point: ``dealradar <command>``."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from dealradar import __version__
from dealradar.core import hu
from dealradar.core.config import get_settings
from dealradar.core.errors import DealRadarError

UI_APP = Path(__file__).resolve().parent / "ui" / "app.py"

# Passed explicitly so the security settings hold even if .streamlit/config.toml is not found
# (Streamlit only reads it from the current working directory).
STREAMLIT_FLAGS = (
    "--server.address=127.0.0.1",
    "--server.headless=true",
    "--server.enableXsrfProtection=true",
    "--browser.gatherUsageStats=false",
    "--browser.serverAddress=127.0.0.1",
    "--client.toolbarMode=viewer",
)


_EVENT = {
    "SOURCE_STARTED": "indul",
    "SOURCE_FINISHED": "kész",
    "SOURCE_SKIPPED": "kihagyva",
}


def _cmd_db_upgrade(_: argparse.Namespace) -> int:
    from dealradar.services.schema import upgrade_database

    backup = upgrade_database(get_settings())
    print(f"Az adatbázis naprakész: {get_settings().db_path}")
    print(f"Mentés: {backup}" if backup else "Mentés: nem kellett (új adatbázis)")
    return 0


def _cmd_db_status(_: argparse.Namespace) -> int:
    from dealradar.services.app_context import build_app_context
    from dealradar.services.schema import schema_status

    ctx = build_app_context()
    st = schema_status(ctx.db.engine)
    print(
        f"Séma: {hu.label('schema_state', st.state)} ({st.state})  jelenlegi={st.current}  "
        f"legfrissebb={st.head}  adatbázis={ctx.settings.db_path}"
    )
    return 0 if st.ready else 1


def _cmd_db_backup(_: argparse.Namespace) -> int:
    from dealradar.db.lock import WriterLock
    from dealradar.services.backup import backup_database

    settings = get_settings()
    settings.ensure_dirs()
    with WriterLock(settings.lock_path, settings.lock_timeout_s):
        path = backup_database(settings)
    print(f"Mentés: {path}" if path else "Nincs mit menteni (nincs adatbázis).")
    return 0


def _cmd_health(_: argparse.Namespace) -> int:
    from dealradar.services.app_context import build_app_context
    from dealradar.services.health import Status, overall, run_health_checks

    ctx = build_app_context()
    results = run_health_checks(ctx.settings, ctx.db)
    for r in results:
        print(f"[{r.status:<4}] {hu.label('health_check', r.name):<20} {r.detail}")
    status = overall(results)
    print(f"Összesítve: {status} ({hu.label('health_status', status)})")
    return 1 if status is Status.FAIL else 0


def _cmd_ui(args: argparse.Namespace) -> int:
    env = dict(os.environ)
    env["DEALRADAR_DATA_DIR"] = str(get_settings().resolved_data_dir)  # same DB regardless of cwd
    cmd = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(UI_APP),
        *STREAMLIT_FLAGS,
        f"--server.port={args.port}",
    ]
    return subprocess.call(cmd, env=env)


def _cmd_refresh(args: argparse.Namespace) -> int:
    from dealradar.core.enums import RefreshScope
    from dealradar.services.app_context import build_app_context
    from dealradar.services.refresh import RefreshEvent, refresh

    ctx = build_app_context()
    if args.source:
        scope, target = RefreshScope.SOURCE, args.source
    elif args.category:
        scope, target = RefreshScope.CATEGORY, args.category.upper()
    else:
        scope, target = RefreshScope.ALL, None

    def show(e: RefreshEvent) -> None:
        if e.kind in ("SOURCE_STARTED", "SOURCE_FINISHED", "SOURCE_SKIPPED"):
            print(
                f"[{e.done_sources}/{e.total_sources}] {_EVENT.get(e.kind, e.kind)}: "
                f"{e.source_key} {e.message}"
            )

    report = refresh(ctx.db, scope, target, progress=show)
    for x in report.sources:
        print(
            f"  {x.source_key:<14} {hu.label('run_status', x.status):<11} letöltve={x.fetched} "
            f"új={x.new_observations} ismétlődő={x.duplicates} hibás={x.failed} "
            f"újrapróbálás={x.retries} gyorsítótárból={x.cache_hits}"
        )
    print(f"{report.job_id}. frissítés: {hu.label('run_status', report.status)}")
    return 0 if report.status.value in ("OK", "PARTIAL") else 1


def _cmd_sources_list(_: argparse.Namespace) -> int:
    from dealradar.services.app_context import build_app_context
    from dealradar.services.refresh import freshness

    ctx = build_app_context()
    rows = freshness(ctx.db)
    if not rows:
        print("Nincs regisztrált forrás.")
    for f in rows:
        last = hu.when(f.last_success_at) if f.last_success_at else "még soha"
        print(
            f"{f.source_key:<14} {hu.label('access_method', f.access_method):<20} "
            f"{hu.label('source_status', f.status):<11} utolsó sikeres: {last}"
            f"{'  ELAVULT' if f.stale else ''}"
        )
    return 0


def _cmd_demo_seed(args: argparse.Namespace) -> int:
    from dealradar.services.app_context import build_app_context
    from dealradar.services.demo import seed_demo

    if not args.i_understand_this_is_synthetic:
        print(
            "Elutasítva: a demóadatok szintetikusak. Használj külön DEALRADAR_DATA_DIR mappát, "
            "és add meg: --i-understand-this-is-synthetic.",
            file=sys.stderr,
        )
        return 2
    ctx = build_app_context()
    result = seed_demo(ctx.db, days=args.days)
    print(
        f"Demóadatok kész: {result['offers']} ajánlat, {result['days']} nap előzmény, "
        f"{result['synthetic_sales']} szintetikus lezárt eladás."
    )
    return 0


def _cmd_notify_test(_: argparse.Namespace) -> int:
    from dealradar.services.app_context import build_app_context
    from dealradar.services.notify import send_test_message

    ctx = build_app_context()
    if not ctx.settings.telegram_enabled:
        print("A Telegram nincs beállítva (nem kötelező). Az értesítések az appban jelennek meg.")
        return 0
    ok, error = send_test_message(ctx.db)
    print("Telegram-tesztüzenet elküldve." if ok else f"A Telegram-teszt sikertelen: {error}")
    return 0 if ok else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dealradar", description="DealRadar HU")
    parser.add_argument("--version", action="version", version=f"dealradar {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    db = sub.add_parser("db", help="adatbázis-műveletek").add_subparsers(
        dest="db_cmd", required=True
    )
    db.add_parser("upgrade", help="mentés, majd frissítés a legújabb sémára").set_defaults(
        func=_cmd_db_upgrade
    )
    db.add_parser("status", help="a séma állapota").set_defaults(func=_cmd_db_status)
    db.add_parser("backup", help="adatbázis-mentés készítése").set_defaults(func=_cmd_db_backup)

    sub.add_parser("health", help="rendszerállapot-ellenőrzés").set_defaults(func=_cmd_health)

    rf = sub.add_parser("refresh", help="források frissítése (alapból mind)")
    group = rf.add_mutually_exclusive_group()
    group.add_argument("--source", help="egy forrás kulcsa")
    group.add_argument(
        "--category", choices=["TECH", "APPAREL", "FOOD", "HOME", "tech", "apparel", "food", "home"]
    )
    group.add_argument("--all", action="store_true", help="minden aktív forrás (alapértelmezés)")
    rf.set_defaults(func=_cmd_refresh)

    src = sub.add_parser("sources", help="forrásnyilvántartás").add_subparsers(
        dest="src_cmd", required=True
    )
    src.add_parser("list", help="források utolsó frissítéssel és elavultsággal").set_defaults(
        func=_cmd_sources_list
    )

    demo = sub.add_parser("demo", help="szintetikus demóadatok").add_subparsers(
        dest="demo_cmd", required=True
    )
    seed = demo.add_parser(
        "seed", help="demóforrások regisztrálása és szintetikus előzmények készítése"
    )
    seed.add_argument("--days", type=int, default=14)
    seed.add_argument("--i-understand-this-is-synthetic", action="store_true")
    seed.set_defaults(func=_cmd_demo_seed)

    nt = sub.add_parser("notify", help="értesítések").add_subparsers(
        dest="notify_cmd", required=True
    )
    nt.add_parser("test", help="Telegram-tesztüzenet küldése (ha be van állítva)").set_defaults(
        func=_cmd_notify_test
    )

    ui = sub.add_parser("ui", help="a felület indítása (csak 127.0.0.1)")
    ui.add_argument("--port", type=int, default=8501)
    ui.set_defaults(func=_cmd_ui)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        code: int = args.func(args)
    except DealRadarError as exc:
        print(f"hiba: {exc}", file=sys.stderr)
        return 2
    return code


if __name__ == "__main__":
    sys.exit(main())

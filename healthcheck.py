#!/usr/bin/env python3
"""
Health checker for web apps and REST APIs.

Modes:
  python healthcheck.py services.json           # JSON config file
  python healthcheck.py --url https://example.com  # Single URL
  python healthcheck.py --db                    # Read services from MySQL
  python healthcheck.py --daily                 # Full daily run: DB → check → save → Telegram
  python healthcheck.py --init-db               # Create MySQL tables
"""

import argparse
import json
import os
import sys
import time
import asyncio
from pathlib import Path
from datetime import datetime, timezone, date
from dataclasses import dataclass, field, asdict
from typing import Optional

try:
    import httpx
except ImportError:
    print("Missing httpx. Install: pip install httpx", file=sys.stderr)
    sys.exit(1)

try:
    from rich.console import Console
    from rich.table import Table
    from rich import box
except ImportError:
    print("Missing rich. Install: pip install rich", file=sys.stderr)
    sys.exit(1)

# ── Load .env ──────────────────────────────────────────────────────────────
_env_path = Path(__file__).parent / ".env.healthcheck"
if _env_path.exists():
    for _line in _env_path.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            k, v = _line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

# ── Config from environment ────────────────────────────────────────────────
DB_CONFIG = {
    "host": os.getenv("HC_DB_HOST", "localhost"),
    "port": int(os.getenv("HC_DB_PORT", "3306")),
    "user": os.getenv("HC_DB_USER", "root"),
    "password": os.getenv("HC_DB_PASSWORD", ""),
    "database": os.getenv("HC_DB_NAME", "healthcheck"),
}

TELEGRAM_BOT_TOKEN = os.getenv("HC_TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("HC_TELEGRAM_CHAT_ID", "")

console = Console()

try:
    import pymysql
    HAS_MYSQL = True
except ImportError:
    HAS_MYSQL = False


# ── Data ───────────────────────────────────────────────────────────────────
@dataclass
class CheckResult:
    name: str
    url: str
    status: int
    ok: bool
    elapsed_ms: float
    error: Optional[str] = None
    body_match: Optional[bool] = None
    checked_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    )


# ── HTTP check ─────────────────────────────────────────────────────────────
async def check_one(client: httpx.AsyncClient, svc: dict) -> CheckResult:
    name = svc.get("name", svc["url"])
    url = svc["url"]
    method = svc.get("method", "GET").upper()
    timeout = svc.get("timeout", 10)
    headers = svc.get("headers", {})
    if isinstance(headers, str):
        try:
            headers = json.loads(headers)
        except Exception:
            headers = {}
    expect_status = svc.get("expect_status", 200)
    expect_body = svc.get("expect_body")

    start = time.monotonic()
    try:
        resp = await client.request(method, url, headers=headers, timeout=timeout)
        elapsed = (time.monotonic() - start) * 1000
        ok = resp.status_code == expect_status
        body_match = None

        if expect_body is not None:
            try:
                body_match = expect_body in resp.text
                if not body_match:
                    ok = False
            except Exception:
                body_match = False
                ok = False

        return CheckResult(
            name=name,
            url=url,
            status=resp.status_code,
            ok=ok,
            elapsed_ms=round(elapsed, 1),
            body_match=body_match,
        )
    except Exception as e:
        elapsed = (time.monotonic() - start) * 1000
        return CheckResult(
            name=name,
            url=url,
            status=0,
            ok=False,
            elapsed_ms=round(elapsed, 1),
            error=str(e),
        )


async def run_checks(services: list[dict]) -> list[CheckResult]:
    limits = httpx.Limits(max_connections=50)
    async with httpx.AsyncClient(limits=limits, follow_redirects=True) as client:
        tasks = [check_one(client, svc) for svc in services]
        return await asyncio.gather(*tasks)


# ── JSON file I/O ──────────────────────────────────────────────────────────
def load_services_from_json(path: Path) -> list[dict]:
    raw = json.loads(path.read_text())
    if isinstance(raw, dict):
        raw = raw.get("services", [])
    return raw


def save_json(results: list[CheckResult], path: Path):
    data = {
        "checked_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "summary": {"total": len(results), "healthy": sum(1 for r in results if r.ok)},
        "services": [asdict(r) for r in results],
    }
    path.write_text(json.dumps(data, indent=2))
    console.print(f"\n[dim]Results saved → {path}[/dim]")


# ── Console output ─────────────────────────────────────────────────────────
def print_table(results: list[CheckResult]):
    table = Table(box=box.ROUNDED, title="Health Check Results")
    table.add_column("Service", style="cyan")
    table.add_column("URL", max_width=50)
    table.add_column("Status", justify="center")
    table.add_column("Time", justify="right")
    table.add_column("Body Match", justify="center")

    for r in results:
        status_style = "green" if r.ok else "red bold"
        status_str = str(r.status) if r.status else "ERR"
        body_str = ""
        if r.body_match is True:
            body_str = "[green]✓[/]"
        elif r.body_match is False:
            body_str = "[red]✗[/]"
        error_suffix = f"  [dim]({r.error})[/dim]" if r.error else ""
        table.add_row(
            r.name,
            r.url + error_suffix,
            f"[{status_style}]{status_str}[/]",
            f"{r.elapsed_ms:.0f}ms",
            body_str,
        )
    console.print(table)


def print_summary(results: list[CheckResult]):
    total = len(results)
    ok_count = sum(1 for r in results if r.ok)
    ko_count = total - ok_count
    style = "green" if ko_count == 0 else "red bold"
    console.print(f"\n[{style}]✓ {ok_count}/{total} services healthy[/]")
    if ko_count:
        console.print("[red]✗ Failing:[/red]")
        for r in results:
            if not r.ok:
                console.print(
                    f"  [red]• {r.name}[/red] ({r.url}) — {r.error or f'status {r.status}'}"
                )


# ── MySQL helpers ──────────────────────────────────────────────────────────
def get_db():
    if not HAS_MYSQL:
        print("Missing pymysql. Install: pip install pymysql", file=sys.stderr)
        sys.exit(1)
    return pymysql.connect(**DB_CONFIG, cursorclass=pymysql.cursors.DictCursor)


INIT_DB_SQL = """
CREATE TABLE IF NOT EXISTS hc_services (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    name        VARCHAR(255) NOT NULL,
    url         VARCHAR(1024) NOT NULL,
    method      VARCHAR(10) DEFAULT 'GET',
    timeout     INT DEFAULT 10,
    expect_status INT DEFAULT 200,
    expect_body TEXT,
    headers     JSON,
    active      TINYINT(1) DEFAULT 1,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS hc_results (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    service_id  INT NOT NULL,
    ok          TINYINT(1) NOT NULL,
    status      INT DEFAULT 0,
    elapsed_ms  FLOAT DEFAULT 0,
    error       TEXT,
    body_match  TINYINT(1),
    checked_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (service_id) REFERENCES hc_services(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS hc_daily_logs (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    run_date    DATE NOT NULL UNIQUE,
    total       INT NOT NULL,
    healthy     INT NOT NULL,
    failed      INT NOT NULL,
    summary     JSON,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""

SEED_SQL = """
INSERT INTO hc_services (name, url, method, timeout, expect_status, expect_body)
VALUES
  ('Mi Web App',    'https://miapp.com',                'GET', 10, 200, '</html>'),
  ('API Health',    'https://api.miapp.com/v1/health',  'GET', 10, 200, '"status":"ok"'),
  ('API Login',     'https://api.miapp.com/v1/auth/ping','POST', 5, 200, NULL)
ON DUPLICATE KEY UPDATE name=name;
"""


def init_db():
    conn = get_db()
    with conn.cursor() as cur:
        for statement in INIT_DB_SQL.split(";"):
            s = statement.strip()
            if s:
                cur.execute(s)
    conn.commit()
    conn.close()
    console.print("[green]✓ MySQL tables created[/]")


def seed_db():
    conn = get_db()
    with conn.cursor() as cur:
        for statement in SEED_SQL.split(";"):
            s = statement.strip()
            if s:
                try:
                    cur.execute(s)
                except Exception as e:
                    console.print(f"[yellow]Seed warning: {e}[/]")
    conn.commit()
    conn.close()
    console.print("[green]✓ Seed data inserted[/]")


def load_services_from_db(only_active: bool = True) -> list[dict]:
    conn = get_db()
    try:
        with conn.cursor() as cur:
            where = "WHERE active = 1" if only_active else ""
            cur.execute(f"SELECT * FROM hc_services {where} ORDER BY name")
            rows = cur.fetchall()
            services = []
            for r in rows:
                svc = {
                    "id": r["id"],
                    "name": r["name"],
                    "url": r["url"],
                    "method": r["method"],
                    "timeout": r["timeout"],
                    "expect_status": r["expect_status"],
                    "expect_body": r["expect_body"],
                    "headers": r.get("headers"),
                }
                services.append(svc)
            return services
    finally:
        conn.close()


def save_results_to_db(results: list[CheckResult], services: list[dict]):
    """Save individual check results with service_id mapping."""
    id_map = {s["url"]: s["id"] for s in services if "id" in s}
    conn = get_db()
    try:
        with conn.cursor() as cur:
            for r in results:
                sid = id_map.get(r.url)
                if sid is None:
                    continue
                cur.execute(
                    """INSERT INTO hc_results
                       (service_id, ok, status, elapsed_ms, error, body_match)
                       VALUES (%s, %s, %s, %s, %s, %s)""",
                    (sid, r.ok, r.status, r.elapsed_ms, r.error, r.body_match),
                )
        conn.commit()
    finally:
        conn.close()


def save_daily_log(results: list[CheckResult]):
    conn = get_db()
    today = date.today()
    total = len(results)
    healthy = sum(1 for r in results if r.ok)
    failed = total - healthy
    summary = {
        "checked_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "services": [asdict(r) for r in results],
    }
    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO hc_daily_logs (run_date, total, healthy, failed, summary)
                   VALUES (%s, %s, %s, %s, %s)
                   ON DUPLICATE KEY UPDATE total=VALUES(total), healthy=VALUES(healthy),
                   failed=VALUES(failed), summary=VALUES(summary)""",
                (today, total, healthy, failed, json.dumps(summary)),
            )
        conn.commit()
    finally:
        conn.close()


# ── Telegram ───────────────────────────────────────────────────────────────
async def send_telegram(results: list[CheckResult]):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        console.print("[yellow]⚠ TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set[/]")
        return

    total = len(results)
    healthy = sum(1 for r in results if r.ok)
    failed = total - healthy

    status_emoji = "✅" if failed == 0 else "🔴"
    lines = [
        f"{status_emoji} *Health Check Daily Report*",
        f"📅 {date.today().isoformat()}",
        "",
        f"✓ Healthy: {healthy}/{total}",
    ]

    if failed:
        lines.append(f"✗ Failed:  {failed}/{total}")
        lines.append("")
        lines.append("*Issues detected:*")
        for r in results:
            if not r.ok:
                lines.append(f"  • *{r.name}* — {r.error or f'HTTP {r.status}'}")
    else:
        lines.append("")
        lines.append("All services are operational 🟢")

    summary_data = {
        "ok": sum(1 for r in results if r.ok),
        "total": len(results),
    }
    avg_ms = sum(r.elapsed_ms for r in results) / max(len(results), 1)
    lines.append("")
    lines.append(f"⚡ Avg response: {avg_ms:.0f}ms")

    text = "\n".join(lines)

    async with httpx.AsyncClient(timeout=15) as client:
        try:
            resp = await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={
                    "chat_id": TELEGRAM_CHAT_ID,
                    "text": text,
                    "parse_mode": "Markdown",
                    "disable_web_page_preview": True,
                },
            )
            if resp.status_code == 200:
                console.print("[green]✓ Telegram notification sent[/]")
            else:
                console.print(f"[red]✗ Telegram error: {resp.text}[/]")
        except Exception as e:
            console.print(f"[red]✗ Telegram send failed: {e}[/]")


# ── Main ───────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Health checker for web apps & REST APIs"
    )
    parser.add_argument("config", nargs="?", help="JSON config file with services list")
    parser.add_argument("--url", help="Single URL to check (quick mode)")
    parser.add_argument("--name", help="Name for the single URL")
    parser.add_argument("--expect-status", type=int, default=200, help="Expected HTTP status")
    parser.add_argument("--expect-body", help="Expected substring in response body")
    parser.add_argument("--method", default="GET", help="HTTP method for single URL")
    parser.add_argument("--timeout", type=int, default=10, help="Request timeout in seconds")
    parser.add_argument("--output", "-o", help="Save results to JSON file")
    parser.add_argument("--db", action="store_true", help="Read services from MySQL")
    parser.add_argument("--init-db", action="store_true", help="Create MySQL tables")
    parser.add_argument("--seed", action="store_true", help="Insert sample services into DB")
    parser.add_argument(
        "--daily", action="store_true", help="Full daily: DB → check → save → Telegram"
    )
    args = parser.parse_args()

    # ── DB setup ──
    if args.init_db:
        init_db()
        return
    if args.seed:
        seed_db()
        return

    # ── Load services ──
    services: list[dict] = []

    if args.db or args.daily:
        services = load_services_from_db()
    elif args.config:
        services = load_services_from_json(Path(args.config))
    elif args.url:
        svc = {
            "url": args.url,
            "name": args.name or args.url,
            "method": args.method,
            "timeout": args.timeout,
            "expect_status": args.expect_status,
        }
        if args.expect_body:
            svc["expect_body"] = args.expect_body
        services = [svc]
    else:
        parser.print_help()
        sys.exit(1)

    if not services:
        console.print("[yellow]No services to check[/]")
        return

    # ── Run checks ──
    results = asyncio.run(run_checks(services))

    # ── Output ──
    print_table(results)
    print_summary(results)

    # ── Save results ──
    if args.db or args.daily:
        save_results_to_db(results, services)
        console.print(f"[dim]✓ Results saved to hc_results ({len(results)} rows)[/dim]")

    if args.daily:
        save_daily_log(results)
        asyncio.run(send_telegram(results))
        console.print("[green]✓ Daily run complete (saved + notified)[/]")

    if args.output:
        save_json(results, Path(args.output))
    elif args.config and not args.output:
        out = f"healthcheck_{Path(args.config).stem}_{int(time.time())}.json"
        save_json(results, Path(out))


if __name__ == "__main__":
    main()

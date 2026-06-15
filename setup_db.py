#!/usr/bin/env python3
"""
Database setup for healthcheck monitor.
Creates database, tables, and optional seed data.

Usage:
    python3 setup_db.py              # create DB + tables
    python3 setup_db.py --seed       # + insert sample services
    python3 setup_db.py --drop       # drop all tables
"""

import os
import sys
import json
from pathlib import Path

_ENV_PATH = Path(__file__).parent / ".env.healthcheck"
if _ENV_PATH.exists():
    for _line in _ENV_PATH.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            k, v = _line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

DB_HOST = os.getenv("HC_DB_HOST", "localhost")
DB_PORT = int(os.getenv("HC_DB_PORT", "3306"))
DB_USER = os.getenv("HC_DB_USER", "root")
DB_PASS = os.getenv("HC_DB_PASSWORD", "")
DB_NAME = os.getenv("HC_DB_NAME", "healthcheck")

try:
    import pymysql
except ImportError:
    print("Missing pymysql. Install: pip install pymysql")
    sys.exit(1)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS hc_services (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    name          VARCHAR(255) NOT NULL,
    url           VARCHAR(1024) NOT NULL,
    method        VARCHAR(10) DEFAULT 'GET',
    timeout       INT DEFAULT 10,
    expect_status INT DEFAULT 200,
    expect_body   TEXT,
    headers       JSON,
    active        TINYINT(1) DEFAULT 1,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
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
INSERT INTO hc_services (name, url, method, timeout, expect_status, expect_body) VALUES
    ('Google',          'https://google.com',                     'GET', 10, 200, '<title>'),
    ('Portal Hunity',   'https://portal.hunitybrokers.com',       'GET', 15, 200, NULL),
    ('CRM Innovus',     'https://innovus.gosmartcrm.com',         'GET', 15, 200, NULL),
    ('Excel TypePlan',  'https://cdn.gosmartgroup.us/estandar/typePlan.xlsx', 'GET', 20, 200, NULL);
"""


def get_conn(database=None):
    return pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASS,
        database=database,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )


def create_database():
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(f"CREATE DATABASE IF NOT EXISTS `{DB_NAME}` CHARACTER SET utf8mb4")
        conn.commit()
        print(f"✓ Database '{DB_NAME}' ready")
    finally:
        conn.close()


def create_tables():
    conn = get_conn(DB_NAME)
    try:
        with conn.cursor() as cur:
            for stmt in SCHEMA_SQL.split(";"):
                s = stmt.strip()
                if s:
                    cur.execute(s)
        conn.commit()
        print("✓ Tables created: hc_services, hc_results, hc_daily_logs")
    finally:
        conn.close()


def seed():
    conn = get_conn(DB_NAME)
    try:
        with conn.cursor() as cur:
            for stmt in SEED_SQL.split(";"):
                s = stmt.strip()
                if s:
                    cur.execute(s)
        conn.commit()
        print("✓ Seed data inserted (4 sample services)")
    finally:
        conn.close()


def drop():
    conn = get_conn(DB_NAME)
    try:
        with conn.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS hc_daily_logs")
            cur.execute("DROP TABLE IF EXISTS hc_results")
            cur.execute("DROP TABLE IF EXISTS hc_services")
        conn.commit()
        print("✓ All tables dropped")
    finally:
        conn.close()


def show_config():
    print(f"  Host:     {DB_HOST}:{DB_PORT}")
    print(f"  Database: {DB_NAME}")
    print(f"  User:     {DB_USER}")
    print(f"  Password: {'***' if DB_PASS else '(empty)'}")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Setup healthcheck database")
    parser.add_argument("--seed", action="store_true", help="Insert sample services")
    parser.add_argument("--drop", action="store_true", help="Drop all tables")
    args = parser.parse_args()

    print("HealthCheck — Database Setup")
    print("─" * 40)
    show_config()

    if args.drop:
        drop()
        return

    create_database()
    create_tables()

    if args.seed:
        seed()

    print("─" * 40)
    print("Done.")


if __name__ == "__main__":
    main()

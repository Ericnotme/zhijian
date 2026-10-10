#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
store.py —— 「知荐」SQLite 存储层
================================

表：

    articles   —— 抓来的文章（标题 / 推荐正文 / 来源 / 分类 / 日期 / 链接）
    users      —— 用户（id / 名字 / 兴趣词 JSON / 邮箱）
    feedback   —— 隐式反馈（用户点开/喜欢/不喜欢某篇文章）
    deliveries —— 已推送记录（每个用户收到过哪些文章，用于去重）

只依赖 Python 3 标准库（sqlite3）。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    id        TEXT PRIMARY KEY,
    title     TEXT NOT NULL,
    text      TEXT,
    summary   TEXT,
    source    TEXT,
    category  TEXT,
    date      TEXT,
    url       TEXT,
    first_seen TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS users (
    id        TEXT PRIMARY KEY,
    name      TEXT,
    interests TEXT,
    email     TEXT,
    created   TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS feedback (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    TEXT NOT NULL,
    article_id TEXT NOT NULL,
    action     TEXT NOT NULL,
    ts         TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS deliveries (
    user_id    TEXT NOT NULL,
    article_id TEXT NOT NULL,
    sent_at    TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, article_id)
);
CREATE INDEX IF NOT EXISTS idx_feedback_user ON feedback(user_id);
"""


def connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    _migrate(conn)
    conn.commit()


def _migrate(conn: sqlite3.Connection) -> None:
    """给老库补 email 列（阶段 3 之前建的库没有）。"""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(users)")}
    if "email" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN email TEXT")


# --------------------------------------------------------------------------- #
# articles
# --------------------------------------------------------------------------- #

def upsert_articles(conn: sqlite3.Connection, items: list[dict]) -> int:
    n = 0
    for it in items:
        if conn.execute("SELECT 1 FROM articles WHERE id=?", (it["id"],)).fetchone():
            continue
        conn.execute(
            "INSERT INTO articles (id, title, text, summary, source, category, date, url) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (it["id"], it["title"], it.get("text", ""), it.get("summary", ""),
             it.get("source", ""), it.get("category", ""), it.get("date", ""), it.get("url", "")),
        )
        n += 1
    conn.commit()
    return n


def list_articles(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT id, title, text, summary, source, category, date, url FROM articles"
    ).fetchall()
    return [dict(r) for r in rows]


# --------------------------------------------------------------------------- #
# users
# --------------------------------------------------------------------------- #

def upsert_user(conn: sqlite3.Connection, user_id: str, name: str,
                interests: list[str], email: str = "") -> None:
    conn.execute(
        "INSERT INTO users (id, name, interests, email) VALUES (?,?,?,?) "
        "ON CONFLICT(id) DO UPDATE SET name=excluded.name, interests=excluded.interests, "
        "email=excluded.email",
        (user_id, name, json.dumps(interests, ensure_ascii=False), email or ""),
    )
    conn.commit()


def list_users(conn: sqlite3.Connection) -> list[dict]:
    out = []
    for r in conn.execute("SELECT id, name, interests, email FROM users").fetchall():
        d = dict(r)
        d["interests"] = json.loads(d.get("interests") or "[]")
        out.append(d)
    return out


def get_user(conn: sqlite3.Connection, user_id: str) -> dict | None:
    r = conn.execute("SELECT id, name, interests, email FROM users WHERE id=?", (user_id,)).fetchone()
    if not r:
        return None
    d = dict(r)
    d["interests"] = json.loads(d.get("interests") or "[]")
    return d


# --------------------------------------------------------------------------- #
# feedback
# --------------------------------------------------------------------------- #

def add_feedback(conn: sqlite3.Connection, user_id: str, article_id: str,
                 action: str = "read") -> None:
    conn.execute(
        "INSERT INTO feedback (user_id, article_id, action) VALUES (?,?,?)",
        (user_id, article_id, action),
    )
    conn.commit()


def feedback_article_ids(conn: sqlite3.Connection, user_id: str,
                         actions: tuple = ("read", "like")) -> list[str]:
    q = ",".join("?" for _ in actions)
    rows = conn.execute(
        f"SELECT DISTINCT article_id FROM feedback WHERE user_id=? AND action IN ({q})",
        (user_id, *actions),
    ).fetchall()
    return [r["article_id"] for r in rows]


# --------------------------------------------------------------------------- #
# deliveries（已推送去重）
# --------------------------------------------------------------------------- #

def add_delivery(conn: sqlite3.Connection, user_id: str, article_id: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO deliveries (user_id, article_id) VALUES (?,?)",
        (user_id, article_id),
    )


def delivered_article_ids(conn: sqlite3.Connection, user_id: str) -> set[str]:
    rows = conn.execute("SELECT article_id FROM deliveries WHERE user_id=?", (user_id,)).fetchall()
    return {r["article_id"] for r in rows}


if __name__ == "__main__":
    conn = connect(":memory:")
    init_db(conn)
    upsert_user(conn, "u1", "测试", ["医学", "神经"], "a@b.com")
    upsert_articles(conn, [{"id": "a1", "title": "脑膜瘤", "text": "脑膜瘤 治疗", "summary": "", "source": "Lancet", "category": "医学", "date": "2026-09-25", "url": "x"}])
    add_delivery(conn, "u1", "a1")
    print("用户:", list_users(conn))
    print("已推送:", delivered_article_ids(conn, "u1"))
    print("OK")

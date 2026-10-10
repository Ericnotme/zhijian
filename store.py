#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
store.py —— 「知荐」SQLite 存储层
================================

三张表：

    articles  —— 抓来的文章（标题 / 用于推荐的正文 / 来源 / 分类 / 日期 / 链接）
    users     —— 用户（id / 名字 / 兴趣词 JSON）
    feedback  —— 隐式反馈（用户点开/喜欢/不喜欢某篇文章）

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
    text      TEXT,                 -- title + summary + category，供推荐引擎分词
    summary   TEXT,
    source    TEXT,
    category  TEXT,
    date      TEXT,                 -- YYYY-MM-DD
    url       TEXT,
    first_seen TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS users (
    id        TEXT PRIMARY KEY,
    name      TEXT,
    interests TEXT,                 -- JSON 数组：显式兴趣词
    created   TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS feedback (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    TEXT NOT NULL,
    article_id TEXT NOT NULL,
    action     TEXT NOT NULL,       -- read / like / dislike
    ts         TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_feedback_user ON feedback(user_id);
"""


def connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


# --------------------------------------------------------------------------- #
# articles
# --------------------------------------------------------------------------- #

def upsert_articles(conn: sqlite3.Connection, items: list[dict]) -> int:
    """批量写入/更新文章。返回新增条数。"""
    n = 0
    for it in items:
        cur = conn.execute("SELECT 1 FROM articles WHERE id=?", (it["id"],))
        if cur.fetchone():
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
                interests: list[str]) -> None:
    conn.execute(
        "INSERT INTO users (id, name, interests) VALUES (?,?,?) "
        "ON CONFLICT(id) DO UPDATE SET name=excluded.name, interests=excluded.interests",
        (user_id, name, json.dumps(interests, ensure_ascii=False)),
    )
    conn.commit()


def list_users(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT id, name, interests FROM users").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["interests"] = json.loads(d.get("interests") or "[]")
        out.append(d)
    return out


def get_user(conn: sqlite3.Connection, user_id: str) -> dict | None:
    r = conn.execute("SELECT id, name, interests FROM users WHERE id=?", (user_id,)).fetchone()
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


if __name__ == "__main__":
    conn = connect(":memory:")
    init_db(conn)
    upsert_articles(conn, [{"id": "a1", "title": "脑膜瘤的放射治疗", "text": "脑膜瘤 放射 治疗", "summary": "", "source": "Lancet", "category": "医学", "date": "2026-09-25", "url": "https://doi.org/x"}])
    upsert_user(conn, "u1", "测试用户", ["医学", "神经", "脑"])
    add_feedback(conn, "u1", "a1", "read")
    print("文章:", list_articles(conn))
    print("用户:", list_users(conn))
    print("反馈:", feedback_article_ids(conn, "u1"))
    print("OK")

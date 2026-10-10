#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pipeline.py —— 「知荐」编排层：把 抓取 → 存储 → 推荐 → 反馈 串起来
=================================================================

用法：
    python3 pipeline.py fetch                          # 抓取所有来源并入库
    python3 pipeline.py add-user <id> <名字> "兴趣词,兴趣词"   # 建用户画像
    python3 pipeline.py users                          # 列出用户
    python3 pipeline.py recommend <user_id> [top_k]    # 给某用户算个性化推荐
    python3 pipeline.py feedback <user_id> <article_id> read|like|dislike   # 记隐式反馈
    python3 pipeline.py stats                          # 库统计

配置从 config.json 读取；没有就跑不起来（可先 cp config.example.json config.json 再填 river 令牌）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import fetcher
import deliver
import store
from recommender import Recommender

HERE = Path(__file__).resolve().parent
CONFIG_PATH = HERE / "config.json"


def load_config():
    if not CONFIG_PATH.exists():
        print(f"✘ 缺少 {CONFIG_PATH}\n  先执行：cp config.example.json config.json 并填好 river 令牌")
        sys.exit(1)
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def connect(cfg):
    db = HERE / cfg.get("db", "data/zhijian.db")
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = store.connect(db)
    store.init_db(conn)
    return conn


# --------------------------------------------------------------------------- #
# 命令
# --------------------------------------------------------------------------- #

def cmd_fetch(args):
    cfg = load_config()
    conn = connect(cfg)
    items = fetcher.aggregate(cfg)
    added = store.upsert_articles(conn, items)
    print(f"抓取 {len(items)} 篇，新增入库 {added} 篇")
    print(f"库中共 {len(store.list_articles(conn))} 篇")


def cmd_add_user(args):
    cfg = load_config()
    conn = connect(cfg)
    interests = [x.strip() for x in args.interests.split(",") if x.strip()]
    store.upsert_user(conn, args.user_id, args.name, interests, email=args.email or "")
    print(f"✔ 用户 {args.name}（{args.user_id}）兴趣：{interests}  邮箱：{args.email or '(未设)'}")


def cmd_users(args):
    cfg = load_config()
    conn = connect(cfg)
    for u in store.list_users(conn):
        print(f"  {u['id']:<14} {u['name']:<12} {u['interests']}")


def cmd_recommend(args):
    cfg = load_config()
    conn = connect(cfg)
    user = store.get_user(conn, args.user_id)
    if not user:
        print(f"✘ 用户 {args.user_id} 不存在")
        return 1

    articles = store.list_articles(conn)
    if not articles:
        print("库是空的，先跑 `python3 pipeline.py fetch`")
        return 1

    r = Recommender()
    for a in articles:
        r.add_document(a["id"], a["text"], meta={"title": a["title"], "source": a["source"],
                                                 "category": a["category"], "date": a["date"], "url": a["url"]})
    r.build()

    fb = store.feedback_article_ids(conn, args.user_id)
    profile = r.profile(user["interests"], feedback_ids=fb)

    top_k = args.top_k or 10
    print(f"\n== {user['name']}（{args.user_id}）的个性化推荐 Top{top_k} ==")
    print(f"   兴趣：{'、'.join(user['interests'])}   ·   已反馈 {len(fb)} 篇\n")
    for doc, score in r.rank(profile, top_k=top_k, recency_days=30):
        m = doc["meta"]
        print(f"  {score:.3f}  [{m['date'] or '?'}] {m['title'][:40]}")
        print(f"          · {m['category'] or '—'} · {m['source'] or '—'}")
        print(f"          · {m['url']}")
        print()


def cmd_feedback(args):
    cfg = load_config()
    conn = connect(cfg)
    store.add_feedback(conn, args.user_id, args.article_id, args.action)
    print(f"✔ 已记录 {args.user_id} {args.action} 《{args.article_id}》")


def cmd_stats(args):
    cfg = load_config()
    conn = connect(cfg)
    n_articles = len(store.list_articles(conn))
    n_users = len(store.list_users(conn))
    print(f"文章：{n_articles} 篇    用户：{n_users} 个")
    for u in store.list_users(conn):
        fb = store.feedback_article_ids(conn, u["id"])
        delivered = len(store.delivered_article_ids(conn, u["id"]))
        print(f"  {u['id']:<14} {u['name']:<12} 反馈 {len(fb)} 条  已推送 {delivered} 篇  {u.get('email') or '(无邮箱)'}")


def cmd_deliver_all(args):
    cfg = load_config()
    conn = connect(cfg)
    if not args.no_fetch:
        items = fetcher.aggregate(cfg)
        added = store.upsert_articles(conn, items)
        print(f"抓取 {len(items)} 篇，新增 {added} 篇")
    n = deliver.deliver_all(cfg, conn, top_k=args.top_k, dry_run=args.dry_run)
    if args.dry_run:
        print(f"[dry-run] 完成，将投递 {n} 人")
    else:
        print(f"完成，共投递 {n} 人")
    return 0


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #

def main(argv=None):
    p = argparse.ArgumentParser(prog="pipeline", description="知荐：抓取 → 存储 → 推荐 → 反馈")
    sub = p.add_subparsers(dest="cmd")

    sub.add_parser("fetch", help="抓取所有来源并入库").set_defaults(func=cmd_fetch)

    pa = sub.add_parser("add-user", help="建用户画像")
    pa.add_argument("user_id")
    pa.add_argument("name")
    pa.add_argument("interests", help="兴趣词，逗号分隔")
    pa.add_argument("--email", help="邮箱（用于投递）")
    pa.set_defaults(func=cmd_add_user)

    sub.add_parser("users", help="列出用户").set_defaults(func=cmd_users)

    pr = sub.add_parser("recommend", help="给用户算个性化推荐")
    pr.add_argument("user_id")
    pr.add_argument("top_k", nargs="?", type=int)
    pr.set_defaults(func=cmd_recommend)

    pf = sub.add_parser("feedback", help="记隐式反馈")
    pf.add_argument("user_id")
    pf.add_argument("article_id")
    pf.add_argument("action", choices=["read", "like", "dislike"])
    pf.set_defaults(func=cmd_feedback)

    sub.add_parser("stats", help="库统计").set_defaults(func=cmd_stats)

    pd = sub.add_parser("deliver-all", help="抓取并给所有用户投递个性化 digest")
    pd.add_argument("--dry-run", action="store_true", help="只打印，不发信")
    pd.add_argument("--no-fetch", action="store_true", help="跳过抓取，只投递已有库")
    pd.add_argument("--top-k", type=int, default=10, help="每人几篇（默认 10）")
    pd.set_defaults(func=cmd_deliver_all)

    args = p.parse_args(argv)
    if not getattr(args, "func", None):
        p.print_help()
        return 1
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

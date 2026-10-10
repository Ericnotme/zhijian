#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
deliver.py —— 「知荐」投递层：把每个用户的个性化推荐渲染成邮件并推送
====================================================================

核心闭环：抓取 → 入库 → 算画像 → 推荐 → 去重（deliveries）→ 渲染 → 发信 → 记录。

只依赖 Python 3 标准库。
"""

from __future__ import annotations

import html as htmllib
import smtplib
import ssl
from datetime import datetime
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate, make_msgid

import store
from recommender import Recommender


# --------------------------------------------------------------------------- #
# 渲染
# --------------------------------------------------------------------------- #

def _esc(s):
    return htmllib.escape(s or "", quote=True)


def render_digest(user: dict, ranked: list[tuple[dict, float]],
                  run_date: datetime) -> tuple[str, str, str]:
    """返回 (subject, text, html)。ranked = [(doc, score), ...]"""
    name = user["name"] or user["id"]
    interests = "、".join(user["interests"]) or "（未设兴趣）"
    date_str = run_date.strftime("%Y年%m月%d日")
    n = len(ranked)
    subject = f"【知荐】{name}，{date_str}为你挑了 {n} 篇"

    # 纯文本
    tl = [f"知荐 · {date_str}", f"{name}，根据你的兴趣（{interests}），今天为你推荐 {n} 篇：", ""]
    for doc, score in ranked:
        m = doc["meta"]
        meta = " · ".join(x for x in [m.get("source"), m.get("category"), m.get("date")] if x)
        tl.append(f"· {m['title']}")
        if meta:
            tl.append(f"  {meta}")
        tl.append(f"  {m.get('url','')}")
        tl.append("")
    tl.append("— 知荐 · 算法推荐取代人工编辑")
    text = "\n".join(tl)

    # HTML
    accent = "#c1350a"  # 头条红
    parts = [
        '<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        f"<title>{_esc(subject)}</title></head>",
        '<body style="margin:0;padding:0;background:#f5f6f7;">',
        '<div style="max-width:640px;margin:0 auto;padding:24px 16px;'
        'font-family:-apple-system,BlinkMacSystemFont,\'PingFang SC\',\'Microsoft YaHei\',sans-serif;'
        'color:#222;">',
        f'<div style="font-size:20px;font-weight:700;color:{accent};">知荐</div>',
        f'<div style="font-size:13px;color:#888;margin-top:2px;">{date_str} · 算法推荐取代人工编辑</div>',
        f'<p style="font-size:14px;color:#444;margin:16px 0 6px;">'
        f'{_esc(name)}，根据你的兴趣（{_esc(interests)}），今天为你推荐 {n} 篇：</p>',
    ]
    for doc, score in ranked:
        m = doc["meta"]
        meta = " · ".join(x for x in [m.get("source"), m.get("category"), m.get("date")] if x)
        parts.append(
            '<div style="padding:13px 15px;margin-bottom:10px;background:#fff;'
            'border-radius:8px;border:1px solid #ececec;">'
            f'<a href="{_esc(m.get("url",""))}" style="font-size:15.5px;font-weight:600;'
            f'color:#222;text-decoration:none;line-height:1.45;">{_esc(m["title"])}</a>'
            f'<div style="font-size:12px;color:#999;margin:6px 0;">{_esc(meta)}</div>'
            + (
                f'<div style="font-size:13px;color:#555;line-height:1.6;">{_esc(m.get("summary","")[:120])}</div>'
                if m.get("summary")
                else ""
            )
            + f'<div style="margin-top:8px;"><a href="{_esc(m.get("url",""))}" '
            f'style="font-size:12px;color:{accent};text-decoration:none;">查看原文 →</a></div>'
            + "</div>"
        )
    parts.append(
        '<div style="margin-top:20px;font-size:11.5px;color:#aaa;line-height:1.7;">'
        '内容版权归原作者与出版方所有，仅供个人阅读。推荐由算法自动生成。</div>'
        "</div></body></html>"
    )
    return subject, text, "".join(parts)


# --------------------------------------------------------------------------- #
# 发信
# --------------------------------------------------------------------------- #

def send_email(cfg: dict, to_addr: str, subject: str, text: str, html: str) -> None:
    em = cfg.get("smtp") or {}
    host, port = em.get("smtp_host"), int(em.get("smtp_port") or 465)
    user, pwd = em.get("username"), em.get("password")
    sender = em.get("from_addr") or user

    if not host or not sender or not to_addr:
        raise RuntimeError("邮件配置不完整（smtp_host / from_addr / 用户邮箱）")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = formataddr((str(Header(em.get("from_name", "知荐"), "utf-8")), sender))
    msg["To"] = to_addr
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid()
    msg.attach(MIMEText(text, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))

    security = (em.get("security") or "ssl").lower()
    if security == "ssl":
        server = smtplib.SMTP_SSL(host, port, timeout=30, context=ssl.create_default_context())
    else:
        server = smtplib.SMTP(host, port, timeout=30)
        server.ehlo()
        if security == "starttls":
            server.starttls(context=ssl.create_default_context())
            server.ehlo()
    try:
        if user:
            server.login(user, pwd)
        server.sendmail(sender, [to_addr], msg.as_string())
    finally:
        try:
            server.quit()
        except Exception:
            pass


# --------------------------------------------------------------------------- #
# 投递
# --------------------------------------------------------------------------- #

def build_recommender(conn) -> Recommender:
    r = Recommender()
    for a in store.list_articles(conn):
        r.add_document(a["id"], a["text"], meta={
            "title": a["title"], "source": a["source"], "category": a["category"],
            "date": a["date"], "url": a["url"], "summary": a.get("summary", ""),
        })
    r.build()
    return r


def recommend_for_user(conn, r: Recommender, user: dict, top_k: int,
                       exclude_delivered: bool = True) -> list[tuple[dict, float]]:
    fb = store.feedback_article_ids(conn, user["id"])
    profile = r.profile(user["interests"], feedback_ids=fb)
    exclude = store.delivered_article_ids(conn, user["id"]) if exclude_delivered else set()
    return r.rank(profile, exclude_ids=exclude, top_k=top_k, recency_days=30)


def deliver_all(cfg: dict, conn, top_k: int = 10, dry_run: bool = False) -> int:
    """给所有有邮箱的用户投递个性化 digest。返回投递人数。"""
    r = build_recommender(conn)
    sent = 0
    for user in store.list_users(conn):
        if not user.get("email"):
            print(f"跳过 {user['name']}（{user['id']}）：未设置邮箱")
            continue
        ranked = recommend_for_user(conn, r, user, top_k)
        if not ranked:
            print(f"跳过 {user['name']}（{user['id']}）：没有新推荐")
            continue
        subject, text, html = render_digest(user, ranked, datetime.now())
        sent += 1
        if dry_run:
            print(f"[dry-run] {user['name']} → {user['email']}：{len(ranked)} 篇")
            print(f"         主题：{subject}")
            continue
        send_email(cfg, user["email"], subject, text, html)
        for doc, _ in ranked:
            store.add_delivery(conn, user["id"], doc["id"])
        conn.commit()
        print(f"✔ 已投递 {user['name']} → {user['email']}：{len(ranked)} 篇")
    return sent


if __name__ == "__main__":
    print("deliver.py —— 请通过 pipeline.py 调用：python3 pipeline.py deliver-all [--dry-run]")

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
webapp.py —— 「知荐」Web 界面
=============================

标准库 http.server 实现，零依赖。启动后浏览器打开 http://127.0.0.1:8000

页面：
    /                首页（用户列表 + 注册入口）
    /signup          注册：填名字 + 兴趣词 + 邮箱
    /u/<user_id>     千人千面的个性化 feed（每篇带 👍喜欢 / 👎不感兴趣）
    /feedback        POST：记录反馈（点击按钮触发）
    /api/feed/<id>   JSON 形式的 feed（调试用）

推荐用 recommender2.BlendedRecommender（内容 + 协同过滤 + 新鲜度 两段式）。

运行：
    python3 webapp.py
"""

from __future__ import annotations

import html as htmllib
import json
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import store
from recommender import Recommender
from recommender2 import BlendedRecommender, CollaborativeRecommender

HERE = Path(__file__).resolve().parent
CONFIG_PATH = HERE / "config.json"
DB_PATH = HERE / "data" / "zhijian.db"
PORT = 8000

ACCENT = "#c1350a"  # 头条红


def esc(s):
    return htmllib.escape(str(s or ""), quote=True)


def load_config():
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return {"db": "data/zhijian.db"}


def connect():
    conn = store.connect(HERE / load_config().get("db", "data/zhijian.db"))
    store.init_db(conn)
    return conn


def load_blender(conn):
    """从库里构建两段式推荐引擎（内容 + 协同过滤）。"""
    content = Recommender()
    for a in store.list_articles(conn):
        content.add_document(a["id"], a["text"], meta={
            "title": a["title"], "source": a["source"], "category": a["category"],
            "date": a["date"], "url": a["url"], "summary": a.get("summary", ""),
        })
    content.build()

    collab = CollaborativeRecommender()
    for u in store.list_users(conn):
        for aid in store.feedback_article_ids(conn, u["id"], actions=("read", "like")):
            collab.add_feedback(u["id"], aid)
    collab.build()
    return BlendedRecommender(content, collab)


# --------------------------------------------------------------------------- #
# HTML 模板
# --------------------------------------------------------------------------- #

def page(title, body):
    return f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title>
<style>
body{{margin:0;font-family:-apple-system,BlinkMacSystemFont,'PingFang SC','Microsoft YaHei',sans-serif;
background:#f5f6f7;color:#222}}
.wrap{{max-width:640px;margin:0 auto;padding:20px 16px 40px}}
.brand{{font-size:22px;font-weight:800;color:{ACCENT}}}
.sub{{font-size:12px;color:#999;margin-top:2px}}
h1{{font-size:16px;margin:20px 0 8px}}
.card{{background:#fff;border:1px solid #eee;border-radius:8px;padding:13px 15px;margin-bottom:10px}}
.card a.t{{font-size:15px;font-weight:600;color:#222;text-decoration:none}}
.card .meta{{font-size:12px;color:#999;margin:5px 0}}
.card .sum{{font-size:13px;color:#555;line-height:1.6}}
.btn{{display:inline-block;margin-top:8px;margin-right:8px;font-size:12px;color:{ACCENT};
text-decoration:none;border:1px solid {ACCENT};border-radius:14px;padding:3px 12px}}
button.b{{font-size:12px;border:1px solid #ddd;border-radius:14px;padding:4px 12px;background:#fff;color:#666;cursor:pointer;margin-right:6px}}
button.b:hover{{border-color:{ACCENT};color:{ACCENT}}}
input,textarea{{width:100%;box-sizing:border-box;padding:9px;margin:6px 0;border:1px solid #ddd;border-radius:6px;font-size:14px}}
ul{{padding-left:18px}} li{{margin:6px 0}}
a{{color:{ACCENT}}}
</style></head><body><div class="wrap">
<div class="brand">知荐 <span style="font-weight:400;font-size:13px;color:#999">算法推荐取代人工编辑</span></div>
<div class="sub">千人千面 · 信息找人</div>
{body}
</div></body></html>"""


# --------------------------------------------------------------------------- #
# 视图
# --------------------------------------------------------------------------- #

def render_home(conn):
    users = store.list_users(conn)
    n_articles = len(store.list_articles(conn))
    li = "".join(
        f'<li><a href="/u/{esc(u["id"])}">{esc(u["name"])}</a> '
        f'<span style="color:#999">兴趣：{esc("、".join(u["interests"]))}</span></li>'
        for u in users
    )
    body = f"""
<h1>用户</h1>
<p style="color:#666;font-size:13px">库中共 {n_articles} 篇文章，{len(users)} 位用户。</p>
<ul>{li or '<li>还没有用户，<a href="/signup">注册一个</a></li>'}</ul>
<a class="btn" href="/signup">+ 注册新用户</a>
"""
    return page("知荐", body)


def render_signup():
    body = """
<h1>注册</h1>
<form method="post" action="/signup">
  <input name="name" placeholder="你的名字" required>
  <input name="interests" placeholder="兴趣词，逗号分隔。如：心理学,大脑,神经,记忆">
  <input name="email" placeholder="邮箱（用于每日推送，可选）">
  <input type="submit" value="创建" style="background:#c1350a;color:#fff;border:none">
</form>
"""
    return page("知荐 · 注册", body)


def render_feed(conn, user_id, blender):
    user = store.get_user(conn, user_id)
    if not user:
        return page("知荐", f'<h1>用户不存在</h1><a class="btn" href="/">返回</a>'), 404
    ranked = blender.recommend(user_id, user["interests"], top_k=20)
    fb = store.feedback_article_ids(conn, user_id)
    cards = []
    for doc, score in ranked:
        m = doc["meta"]
        meta = " · ".join(x for x in [m.get("source"), m.get("category"), m.get("date")] if x)
        cards.append(f"""
<div class="card">
  <a class="t" href="{esc(m.get('url',''))}" target="_blank">{esc(m["title"])}</a>
  <div class="meta">{esc(meta)} · 匹配 {score:.3f}</div>
  <div class="sum">{esc((m.get("summary") or "")[:120])}</div>
  <form method="post" action="/feedback" style="display:inline">
    <input type="hidden" name="user_id" value="{esc(user_id)}">
    <input type="hidden" name="article_id" value="{esc(doc['id'])}">
    <input type="hidden" name="action" value="like">
    <button class="b">👍 喜欢</button>
  </form>
  <form method="post" action="/feedback" style="display:inline">
    <input type="hidden" name="user_id" value="{esc(user_id)}">
    <input type="hidden" name="article_id" value="{esc(doc['id'])}">
    <input type="hidden" name="action" value="dislike">
    <button class="b">👎 不感兴趣</button>
  </form>
</div>""")
    body = f"""
<h1>{esc(user['name'])} 的个性化推荐</h1>
<p style="color:#999;font-size:13px">兴趣：{esc("、".join(user["interests"]))} · 已反馈 {len(fb)} 篇</p>
{"".join(cards) or "<p>还没有推荐，先 <a href=\"/\">抓取内容</a></p>"}
<a class="btn" href="/">返回</a>
"""
    return page(f"知荐 · {user['name']}", body), 200


# --------------------------------------------------------------------------- #
# HTTP 处理
# --------------------------------------------------------------------------- #

class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="text/html; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body.encode("utf-8"))))
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))

    def _redirect(self, location):
        self.send_response(302)
        self.send_header("Location", location)
        self.end_headers()

    def do_GET(self):
        conn = connect()
        path = urllib.parse.urlparse(self.path).path
        try:
            if path == "/":
                self._send(200, render_home(conn))
            elif path == "/signup":
                self._send(200, render_signup())
            elif path.startswith("/u/"):
                user_id = path.split("/u/", 1)[1].strip("/")
                blender = load_blender(conn)
                body, code = render_feed(conn, user_id, blender)
                self._send(code, body)
            elif path.startswith("/api/feed/"):
                user_id = path.split("/api/feed/", 1)[1].strip("/")
                blender = load_blender(conn)
                ranked = blender.recommend(user_id, store.get_user(conn, user_id)["interests"], top_k=20)
                self._send(200, json.dumps(
                    [{"title": d["meta"]["title"], "url": d["meta"]["url"], "score": round(s, 4)}
                     for d, s in ranked], ensure_ascii=False), "application/json; charset=utf-8")
            else:
                self._send(404, page("知荐", "<h1>404</h1>"))
        except Exception as e:  # noqa: BLE001
            self._send(500, page("知荐", f"<h1>出错了</h1><pre>{esc(e)}</pre>"))
        finally:
            conn.close()

    def do_POST(self):
        conn = connect()
        path = urllib.parse.urlparse(self.path).path
        length = int(self.headers.get("Content-Length", 0))
        form = urllib.parse.parse_qs(self.rfile.read(length).decode("utf-8") or "")
        one = lambda k: (form.get(k) or [""])[0].strip()  # noqa: E731
        try:
            if path == "/feedback":
                store.add_feedback(conn, one("user_id"), one("article_id"), one("action") or "read")
                self._redirect(f"/u/{one('user_id')}")
            elif path == "/signup":
                interests = [x.strip() for x in one("interests").split(",") if x.strip()]
                import hashlib
                uid = hashlib.md5((one("name") + one("email")).encode()).hexdigest()[:8]
                store.upsert_user(conn, uid, one("name") or "新用户", interests, email=one("email"))
                self._redirect(f"/u/{uid}")
            else:
                self._redirect("/")
        finally:
            conn.close()

    def log_message(self, *args):
        pass  # 静默，避免刷屏


def main():
    print(f"知荐 Web 已启动：http://127.0.0.1:{PORT}")
    print("  首页 /  ·  注册 /signup  ·  个性化 feed /u/<user_id>")
    server = HTTPServer(("127.0.0.1", PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetcher.py —— 「知荐」内容聚合层
================================

把多个来源的内容抓回来，归一化成统一结构：

    {"id", "title", "text", "summary", "source", "category", "date", "url"}

     · river.to  —— 付费聚合站的时政/经济/文化/科技文章（需登录令牌）
     · PubMed    —— 医学/记忆/衰老的最新论文（E-utilities API）
     · RSS       —— Nature 系列期刊 + 知识分子 等

只依赖 Python 3 标准库。每个来源都是「尽力而为」：单个来源失败不影响其它来源。
"""

from __future__ import annotations

import html as htmllib
import json
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from html.parser import HTMLParser
from http.cookiejar import MozillaCookieJar

DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

PUBMED_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"


# --------------------------------------------------------------------------- #
# 通用
# --------------------------------------------------------------------------- #

def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", htmllib.unescape(s or "")).strip()


def _strip_tags(s: str) -> str:
    s = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", s or "", flags=re.S | re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    return _clean(s)


def _norm_date(s: str) -> str:
    s = (s or "").strip().replace("Jan.", "Jan").replace("Feb.", "Feb")
    if not s:
        return ""
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%a, %d %b %Y %H:%M:%S %z",
                "%a, %d %b %Y %H:%M:%S %Z", "%Y-%m-%dT%H:%M:%S%z",
                "%Y-%m-%dT%H:%M:%S", "%Y%m%d"):
        try:
            return datetime.strptime(s.strip(), fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    m = re.search(r"(20\d{2})[-/年](\d{1,2})[-/月](\d{1,2})", s)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return ""


def _http_get(url: str, headers: dict | None = None, timeout: int = 25, retries: int = 3) -> str:
    h = {"User-Agent": DEFAULT_UA, "Accept": "*/*"}
    h.update(headers or {})
    req = urllib.request.Request(url, headers=h)
    last = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                cs = r.headers.get_content_charset() or "utf-8"
                return raw.decode(cs, errors="replace")
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(min(2 ** attempt, 6))
    raise RuntimeError(f"请求失败 {url}: {last}")


def _item(doc_id, title, summary, source, category, date, url, extra_text=""):
    text = f"{title} {summary} {extra_text}"
    return {
        "id": doc_id, "title": title, "text": _clean(text),
        "summary": _clean(summary)[:200], "source": source or "",
        "category": category or "", "date": _norm_date(date), "url": url or "",
    }


# --------------------------------------------------------------------------- #
# PubMed
# --------------------------------------------------------------------------- #

_MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
           "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}


def _pubmed_search(term, reldate, retmax, email="", tool="zhijian"):
    params = {"db": "pubmed", "term": term, "retmax": str(retmax),
              "datetype": "pdat", "reldate": str(reldate),
              "sort": "pub_date", "retmode": "json"}
    if email:
        params["email"] = email
    params["tool"] = tool
    url = PUBMED_BASE + "esearch.fcgi?" + urllib.parse.urlencode(params)
    return json.loads(_http_get(url)).get("esearchresult", {}).get("idlist", [])


def _pubmed_fetch(pmids, email="", tool="zhijian"):
    if not pmids:
        return []
    params = {"db": "pubmed", "id": ",".join(pmids), "retmode": "xml"}
    if email:
        params["email"] = email
    params["tool"] = tool
    root = ET.fromstring(_http_get(PUBMED_BASE + "efetch.fcgi?" + urllib.parse.urlencode(params)))

    def local(t):
        return t.split("}")[-1].lower()

    def ymd(y, m, d):
        try:
            yy = int(y)
        except (TypeError, ValueError):
            return ""
        mm = None
        if m:
            m = str(m).strip().lower()
            if m.isdigit():
                mm = int(m)
            elif m[:3] in _MONTHS:
                mm = _MONTHS[m[:3]]
        dd = int(d) if d and str(d).strip().isdigit() else None
        return f"{yy:04d}-{mm:02d}-{dd:02d}" if mm and dd else (f"{yy:04d}-{mm:02d}" if mm else f"{yy:04d}")

    def pub_date(node):
        for el in node.iter():
            if local(el.tag) == "articledate":
                y = m = d = ""
                for c in el.iter():
                    t = local(c.tag)
                    if t == "year":
                        y = (c.text or "").strip()
                    elif t == "month":
                        m = (c.text or "").strip()
                    elif t == "day":
                        d = (c.text or "").strip()
                if y:
                    return ymd(y, m, d)
        for el in node.iter():
            if local(el.tag) == "pubdate":
                y = m = d = med = ""
                for c in el.iter():
                    t = local(c.tag)
                    if t == "year":
                        y = (c.text or "").strip()
                    elif t == "month":
                        m = (c.text or "").strip()
                    elif t == "day":
                        d = (c.text or "").strip()
                    elif t == "medlinedate":
                        med = (c.text or "").strip()
                if med:
                    mm = re.match(r"\s*(\d{4})\s+([A-Za-z]+)(?:\s+(\d{1,2}))?", med)
                    if mm:
                        return ymd(mm.group(1), mm.group(2), mm.group(3) or "")
                if y:
                    return ymd(y, m, d)
        return ""

    out = []
    for art in root.iter():
        if local(art.tag) != "pubmedarticle":
            continue
        title = journal = doi = pmid = ""
        abstracts = []
        for el in art.iter():
            t = local(el.tag)
            if t == "articletitle" and not title and el.text:
                title = el.text.strip()
            elif t == "title" and not journal and el.text:
                journal = el.text.strip()
            elif t == "abstracttext":
                lab = el.attrib.get("Label", "")
                txt = " ".join(el.itertext()).strip()
                if txt:
                    abstracts.append((f"{lab}: " if lab else "") + txt)
            elif t == "articleid":
                idt = el.attrib.get("IdType", "")
                if idt == "doi":
                    doi = (el.text or "").strip()
                elif idt == "pubmed":
                    pmid = (el.text or "").strip()
        url = f"https://doi.org/{doi}" if doi else f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
        out.append(_item(pmid or doi or title, title, " ".join(abstracts),
                         journal, "", pub_date(art), url))
    return out


def fetch_pubmed(cfg: dict) -> list[dict]:
    pub = cfg.get("pubmed") or {}
    if not pub.get("enabled", True):
        return []
    email = cfg.get("email", "")
    reldate = int(pub.get("reldate", 14))
    retmax = int(pub.get("max_per_group", 8))
    items = []
    for group, term in (pub.get("groups") or {}).items():
        try:
            pmids = _pubmed_search(term, reldate, retmax, email=email)
            time.sleep(0.4)
            for it in _pubmed_fetch(pmids, email=email):
                it["category"] = group
                it["text"] += f" {group}"
                items.append(it)
        except Exception as e:  # noqa: BLE001
            print(f"[fetcher] PubMed「{group}」失败：{e}")
    return items


# --------------------------------------------------------------------------- #
# RSS / Atom
# --------------------------------------------------------------------------- #

def fetch_rss(cfg: dict) -> list[dict]:
    rss = cfg.get("rss") or {}
    if not rss.get("enabled", True):
        return []
    max_per = int(rss.get("max_per_feed", 6))
    items = []
    for feed in (rss.get("feeds") or []):
        name = feed.get("name") or feed["url"]
        try:
            root = ET.fromstring(_http_get(feed["url"]))

            def local(t):
                return t.split("}")[-1].lower()

            for node in root.iter():
                if local(node.tag) not in ("item", "entry"):
                    continue
                title = link = desc = date = ""
                for child in node:
                    t = local(child.tag)
                    if t == "title":
                        title = _clean("".join(child.itertext()))
                    elif t in ("link", "guid", "id") and not link:
                        link = (child.attrib.get("href") or "").strip() or _clean("".join(child.itertext()))
                    elif t in ("description", "summary", "content", "encoded") and not desc:
                        desc = _strip_tags("".join(child.itertext()))
                    elif t in ("pubdate", "published", "updated", "date", "issued") and not date:
                        date = _clean("".join(child.itertext()))
                if not title:
                    continue
                desc = re.sub(r"^.*?Published online:\s*[^;]+;\s*doi:\S+\s*", "", desc).strip()
                items.append(_item(link or title, title, desc, name, name, date, link))
                if len([x for x in items if x["source"] == name]) >= max_per:
                    break
        except Exception as e:  # noqa: BLE001
            print(f"[fetcher] RSS「{name}」失败：{e}")
    return items


# --------------------------------------------------------------------------- #
# river.to
# --------------------------------------------------------------------------- #

class _RiverCards(HTMLParser):
    """解析 river.to/occasus 的 streamItem 卡片。"""

    MAX_TOPIC = 30

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.cards = []
        self.cur = {}
        self.mode = None
        self.buf = []
        self.anchor_stack = []
        self.h3_anchor = None
        self.in_divider = False
        self.await_topic = False

    def _take(self):
        t = _clean("".join(self.buf))
        self.buf = []
        return t

    def _ok_topic(self, t):
        if not t or len(t) > self.MAX_TOPIC:
            return False
        if any(ch in t for ch in "。，、；：！？,.;:!?（）()"):
            return False
        if not re.search(r"[\w\u4e00-\u9fff]", t):
            return False
        if t == self.cur.get("summary"):
            return False
        return True

    def _finalize(self):
        c = self.cur
        if c.get("title") and (c.get("url") or "").startswith("http"):
            self.cards.append({
                "title": c.get("title", ""), "url": c.get("url", ""),
                "summary": c.get("summary", ""), "source": c.get("source", ""),
                "date": c.get("date", ""), "topic": c.get("topic", ""),
            })
        self.cur = {}
        self.await_topic = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "a":
            self.anchor_stack.append(a.get("href", ""))
            if "avatar" in a.get("class", ""):
                self.cur["_src_url"] = a.get("href", "")
        elif tag == "img":
            alt = (a.get("alt") or "").strip()
            if alt and self.cur.get("_src_url") and not self.cur.get("source"):
                self.cur["source"] = alt
        elif tag == "h3":
            if self.cur.get("title"):
                self._finalize()
            self.mode = "title"
            self.buf = []
            self.h3_anchor = self.anchor_stack[-1] if self.anchor_stack else None
        elif tag == "h4":
            if "ui-summary" in a.get("class", ""):
                self.mode = "summary"
                self.buf = []
        elif tag == "time":
            self.cur["date"] = a.get("datetime", "")
        elif tag == "span" and "middotDivider" in a.get("class", ""):
            self.in_divider = True

    def handle_endtag(self, tag):
        if tag == "a" and self.anchor_stack:
            self.anchor_stack.pop()
        elif tag == "h3" and self.mode == "title":
            self.cur["title"] = self._take()
            self.cur["url"] = self.h3_anchor or ""
            self.mode = None
        elif tag == "h4" and self.mode == "summary":
            self.cur["summary"] = self._take()
            self.mode = None
        elif tag == "time":
            self.await_topic = True
        elif tag == "span" and self.in_divider:
            self.in_divider = False

    def handle_data(self, data):
        if self.mode in ("title", "summary"):
            self.buf.append(data)
            return
        if self.await_topic and not self.in_divider:
            t = _clean(data)
            if t:
                if self._ok_topic(t):
                    self.cur["topic"] = t
                self.await_topic = False
                self._finalize()

    def close(self):
        super().close()
        if self.cur.get("title"):
            self._finalize()


class RiverClient:
    """river.to 的极简登录 + 抓取会话。"""

    def __init__(self, cfg: dict):
        site = cfg.get("river") or {}
        self.base = site.get("base_url", "https://river.to/occasus").rstrip("/")
        self.login_url = site.get("login_url", "")
        self.sections = site.get("sections") or [""]
        self.timeout = int(site.get("timeout", 30))
        self.delay = float(site.get("delay", 0.5))
        self.ua = site.get("user_agent") or DEFAULT_UA
        self.jar = MozillaCookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self._last = 0.0

    def _get(self, url):
        gap = self.delay - (time.time() - self._last)
        if gap > 0:
            time.sleep(gap)
        req = urllib.request.Request(url, headers={"User-Agent": self.ua})
        try:
            with self.opener.open(req, timeout=self.timeout) as r:
                raw = r.read()
                self._last = time.time()
                return raw.decode(r.headers.get_content_charset() or "utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            if e.code in (404, 410):
                return None
            raise

    def login(self):
        if not self.login_url:
            raise RuntimeError("未配置 river.login_url（wtlwp_token 登录链接）")
        self._get(self.login_url)
        if not any(c.name.startswith("wordpress_logged_in_") for c in self.jar):
            raise RuntimeError("river.to 登录失败：未拿到 wordpress_logged_in_ cookie，令牌可能已过期")

    def fetch(self):
        items = []
        for sec in self.sections:
            url = f"{self.base}/{sec}".rstrip("/")
            try:
                page = self._get(url)
            except Exception as e:  # noqa: BLE001
                print(f"[fetcher] river「{sec or 'home'}」失败：{e}")
                continue
            if page is None:
                continue
            for c in self._parse(page):
                if c["url"].startswith("http"):
                    items.append(_item(
                        c["url"], c["title"], c["summary"], c["source"],
                        c["topic"], c["date"], c["url"],
                    ))
        return items

    @staticmethod
    def _parse(page):
        p = _RiverCards()
        p.feed(page)
        p.close()
        return p.cards


def fetch_river(cfg: dict) -> list[dict]:
    site = cfg.get("river") or {}
    if not site.get("enabled", True) or not site.get("login_url"):
        return []
    client = RiverClient(cfg)
    try:
        client.login()
        return client.fetch()
    except Exception as e:  # noqa: BLE001
        print(f"[fetcher] river.to 失败：{e}")
        return []


# --------------------------------------------------------------------------- #
# 聚合
# --------------------------------------------------------------------------- #

def aggregate(cfg: dict) -> list[dict]:
    """抓取所有启用的来源，返回归一化文章列表。"""
    items = []
    items += fetch_river(cfg)
    items += fetch_pubmed(cfg)
    items += fetch_rss(cfg)
    # 按 id 去重（保留第一个）
    seen = {}
    for it in items:
        seen.setdefault(it["id"], it)
    return list(seen.values())


if __name__ == "__main__":
    import sys
    cfg = {"pubmed": {"enabled": True, "groups": {"衰老": "senescence[tiab] OR longevity[tiab]"}},
           "rss": {"enabled": True, "feeds": [{"name": "Nature Aging", "url": "https://www.nature.com/nataging.rss"}]},
           "river": {"enabled": False}, "email": ""}
    print("== fetcher 自测（PubMed + RSS，不含 river）==")
    for it in aggregate(cfg)[:6]:
        print(f"  [{it['date']}] {it['category']} · {it['source']} · {it['title'][:46]}")
    sys.exit(0)

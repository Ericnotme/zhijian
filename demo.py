#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
demo.py —— 「知荐」千人千面演示
=============================

用真实的抓取样本（data/sample_articles.json，38 篇，来自 river.to 聚合站）
演示「今日头条式」的核心体验：

    同一个内容池，不同画像的人，看到完全不同的 Top 推荐。

    用户A（脑科学爱好者）   → 心理学 / 大脑 / 认知 排前面
    用户B（财经投资者）     → 经济 / 金融 / 市场 排前面
    用户C（文艺青年）       → 文化 / 文学 / 散文 排前面
    用户D（抗衰养生党）     → 衰老 / 长寿 / 医学 排前面

还会演示「隐式反馈」：用户点开某篇文章后，他的画像随之漂移，推荐排序改变——
这就是「信息找人」：不是你去搜，而是内容顺着你的兴趣来找你。

运行：
    python3 demo.py
"""

from __future__ import annotations

import json
from pathlib import Path

from recommender import Recommender

DATA = Path(__file__).parent / "data" / "sample_articles.json"

# 四个画像：显式兴趣词
PERSONAS = {
    "🧠 脑科学爱好者": ["心理学", "大脑", "神经", "记忆", "认知", "意识", "情绪"],
    "📈 财经投资者":   ["经济", "金融", "股市", "市场", "货币", "利率", "央行", "投资"],
    "📚 文艺青年":     ["文学", "诗歌", "散文", "历史", "艺术", "文化", "书"],
    "🧬 抗衰养生党":   ["衰老", "长寿", "老化", "寿命", "医学", "健康", "端粒"],
}


def load_docs():
    items = json.loads(DATA.read_text(encoding="utf-8"))
    return [{
        "id": it["id"],
        "text": f'{it["title"]} {it["summary"]} {it["category"]}',
        "meta": {"title": it["title"], "category": it["category"],
                 "source": it["source"], "date": it["date"]},
    } for it in items]


def show(label, docs, top_k=6):
    print(f"\n{'─' * 66}\n{label}\n{'─' * 66}")
    for doc, score in docs[:top_k]:
        m = doc["meta"]
        print(f"  {score:.3f}  [{m['date']}] {m['title'][:34]}")
        print(f"          · {m['category']} · {m['source']}")


def main():
    print("=" * 66)
    print("知荐 · 千人千面演示 —— 同一个内容池，不同的人，不同的推荐")
    print("=" * 66)

    r = Recommender()
    r.add_documents(load_docs())
    r.build()
    print(f"\n内容池：{len(r.docs)} 篇文章（真实抓取样本）")

    # 1) 四个画像各自的 Top 推荐
    for name, interests in PERSONAS.items():
        prof = r.profile(interests)
        show(f"{name} 的个性化 Top6", r.rank(prof, top_k=6, recency_days=0))

    # 2) 隐式反馈：文艺青年点开两篇「衰老」文章后，画像漂移
    print(f"\n\n{'=' * 66}\n隐式反馈演示\n{'=' * 66}")
    print("用户「📚 文艺青年」原本只看文学。假设他点开了两篇衰老类文章：")
    aging_ids = [
        d["id"] for d in r.docs if d["meta"]["category"] == "衰老/长寿"
    ][:2]
    for i in aging_ids:
        t = next(d for d in r.docs if d["id"] == i)["meta"]["title"]
        print(f"  · 点开：《{t}》")

    prof_before = r.profile(PERSONAS["📚 文艺青年"])
    prof_after = r.profile(PERSONAS["📚 文艺青年"], feedback_ids=aging_ids)

    print("\n点开前 → 文学占主导：")
    for doc, s in r.rank(prof_before, top_k=4):
        print(f"  {s:.3f}  {doc['meta']['title'][:34]}")
    print("\n点开后 → 衰老/医学类被推上来：")
    for doc, s in r.rank(prof_after, top_k=4):
        print(f"  {s:.3f}  {doc['meta']['title'][:34]}")

    print("\n\n结论：用户画像会随着他的行为实时漂移，")
    print("这正是「算法推荐取代人工编辑」的含义 —— 没有编辑定死栏目，")
    print("推荐顺序完全由算法根据每个人的兴趣与行为算出来。")


if __name__ == "__main__":
    main()

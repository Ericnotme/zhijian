#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
recommender2.py —— 「知荐」第二阶段推荐引擎
=============================================

在内容基（TF-IDF + 余弦）之上，加入今日头条式的进阶能力：

1. 协同过滤（item-item collaborative filtering）
   —— 「喜欢这篇文章的人，也喜欢那些」。利用 feedback 表里的隐式反馈，
   算文章与文章之间的共现相似度，从而推荐「你还没看过、但和你口味相近」的内容。

2. 两段式：召回 → 排序（recall + rank）
   —— 召回：内容相似 + 协同相似 + 新鲜热门，三路候选合并
   —— 排序：加权融合（内容分 × α + 协同分 × β + 新鲜度 × γ）

只依赖 Python 3 标准库，与 recommender.py（内容基）搭配使用。
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from datetime import datetime

from recommender import Recommender


# --------------------------------------------------------------------------- #
# 协同过滤（item-item）
# --------------------------------------------------------------------------- #

class CollaborativeRecommender:
    """基于隐式反馈的 item-item 协同过滤。"""

    def __init__(self):
        self.user_items: dict[str, set] = defaultdict(set)   # user -> liked/read items
        self.item_users: dict[str, set] = defaultdict(set)   # item -> users
        self.sim: dict[str, dict[str, float]] = defaultdict(dict)

    def add_feedback(self, user_id: str, item_id: str):
        self.user_items[user_id].add(item_id)
        self.item_users[item_id].add(user_id)

    def build(self):
        """算 item-item 共现相似度（带 log 惩罚热门项）。"""
        self.sim = defaultdict(dict)
        for i, users_i in self.item_users.items():
            co: Counter = Counter()
            for u in users_i:
                for j in self.user_items[u]:
                    if j != i:
                        co[j] += 1
            denom = math.sqrt(len(users_i))
            for j, cnt in co.items():
                self.sim[i][j] = cnt / (denom * math.sqrt(len(self.item_users[j])))

    def score(self, liked_items: list[str], exclude: set, top_n: int = 200) -> dict[str, float]:
        """给定用户喜欢的文章，返回「相似但没看过」的候选打分。"""
        scores: Counter = Counter()
        for i in liked_items:
            for j, s in self.sim.get(i, {}).items():
                if j not in exclude:
                    scores[j] += s
        return dict(scores.most_common(top_n))

    @property
    def ready(self) -> bool:
        return bool(self.sim) or bool(self.user_items)


# --------------------------------------------------------------------------- #
# 两段式混合推荐
# --------------------------------------------------------------------------- #

class BlendedRecommender:
    """
    召回 → 排序：

    召回：内容相似(TF-IDF) ∪ 协同相似(CF) ∪ 新鲜热门
    排序：final = α·内容 + β·协同 + γ·新鲜度
    """

    def __init__(self, content: Recommender, collab: CollaborativeRecommender,
                 alpha: float = 0.5, beta: float = 0.3, gamma: float = 0.2):
        self.content = content
        self.collab = collab
        self.alpha, self.beta, self.gamma = alpha, beta, gamma
        self._doc_by_id = {d["id"]: d for d in content.docs}

    @staticmethod
    def _freshness(date_str, half_life_days=30):
        if not date_str:
            return 0.5
        try:
            d = datetime.strptime(date_str[:10], "%Y-%m-%d")
        except ValueError:
            return 0.5
        days = max(0, (datetime.now() - d).days)
        return 2.0 ** (-days / half_life_days)

    def recommend(self, user_id: str, interests: list[str], top_k: int = 10,
                  recency_days: int = 30) -> list[tuple[dict, float]]:
        """返回 [(doc, score), ...]，doc 的 meta 含 title/source/category/date/url/summary。"""
        liked = list(self.collab.user_items.get(user_id, []))
        exclude = set(liked)

        # ---- 召回 ----
        # 内容相似
        profile = self.content.profile(interests, feedback_ids=liked)
        content_cands = {d["id"]: s for d, s in self.content.rank(profile, top_k=60, recency_days=0)}
        # 协同相似
        collab_cands = self.collab.score(liked, exclude, top_n=60)
        # 新鲜热门（最近的文章兜底）
        fresh_cands = {}
        for d in sorted(self.content.docs, key=lambda x: x["meta"].get("date") or "", reverse=True)[:30]:
            if d["id"] not in exclude:
                fresh_cands[d["id"]] = 1.0

        # ---- 排序 ----
        final: dict[str, float] = {}
        for cid in set(content_cands) | set(collab_cands) | set(fresh_cands):
            c = content_cands.get(cid, 0.0)
            cb = collab_cands.get(cid, 0.0)
            f = self._freshness(self._doc_by_id.get(cid, {}).get("meta", {}).get("date"), recency_days)
            final[cid] = self.alpha * c + self.beta * cb + self.gamma * f

        ranked = sorted(final.items(), key=lambda x: -x[1])
        out = []
        for cid, s in ranked[:top_k]:
            d = self._doc_by_id.get(cid)
            if d:
                out.append((d, s))
        return out

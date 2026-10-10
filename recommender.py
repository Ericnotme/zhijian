#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
recommender.py —— 「知荐」内容基推荐引擎
=====================================

今日头条式产品的 X 因素：**算法推荐取代人工编辑**，实现「信息找人」。
本模块是那个「算法」的最小可运行实现，只依赖 Python 3 标准库。

原理（content-based filtering，基于内容的协同）：

1. 把每篇文章分词 —— 中文按「二字切分」（bigram），英文按单词切分，
   得到一个 token 序列。例如「脑膜瘤的放射治疗」→ [脑膜, 膜瘤, 瘤的, 的放, 放射, 射治, 治疗]。
2. 对全网文章算 IDF（逆文档频率）：越罕见的词权重越高。
3. 每篇文章 → TF-IDF 向量。
4. 每个用户 → 「兴趣画像向量」：
     · 显式兴趣词（用户自己选的标签）
     · + 隐式反馈（用户点开/读完过的文章向量平均，权重更高）
5. 推荐 = 用户画像向量 与 文章向量 的**余弦相似度**，再乘「新鲜度」加成，
   排序取 Top-K。

因为画像不同，同一个内容池会对不同用户产生**完全不同的排序** —— 这就是「千人千面」。

运行自测：
    python3 recommender.py
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta


# --------------------------------------------------------------------------- #
# 分词
# --------------------------------------------------------------------------- #

_HAN = re.compile(r"[\u4e00-\u9fff]")
_LATIN = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    """中文按 2-gram、英文按单词，返回小写 token 列表。"""
    text = (text or "").lower()
    tokens = _LATIN.findall(text)
    han = _HAN.sub("", text)  # 先去掉英文，避免中英混杂
    # 中文连续片段按 2-gram 切
    for run in re.findall(r"[\u4e00-\u9fff]+", text):
        tokens += [run[i:i + 2] for i in range(len(run) - 1)]
    return tokens


# --------------------------------------------------------------------------- #
# 推荐引擎
# --------------------------------------------------------------------------- #

class Recommender:
    """极简内容基推荐引擎。"""

    def __init__(self):
        self.docs: list[dict] = []
        self.idf: dict[str, float] = {}
        self._built = False

    # -- 建库 ---------------------------------------------------------------

    def add_document(self, doc_id, text: str, meta: dict | None = None):
        """加入一篇文章。text 建议是「标题 + 摘要 + 话题标签」拼起来。"""
        tokens = tokenize(text)
        self.docs.append({
            "id": doc_id,
            "tokens": tokens,
            "tf": Counter(tokens),
            "meta": meta or {},
        })
        self._built = False

    def add_documents(self, items):
        """批量加入。[{id, text, meta}]"""
        for it in items:
            self.add_document(it["id"], it["text"], it.get("meta"))

    def build(self):
        """计算 IDF。加完文档后调用一次。"""
        n = len(self.docs)
        df: Counter = Counter()
        for d in self.docs:
            for t in set(d["tokens"]):
                df[t] += 1
        self.idf = {t: math.log(n / (1 + df[t])) + 1.0 for t in df}
        self._built = True
        return self

    # -- 向量 ---------------------------------------------------------------

    def vector(self, tokens: list[str]) -> dict[str, float]:
        """tokens -> TF-IDF 向量。"""
        if not self._built:
            self.build()
        tf = Counter(tokens)
        total = len(tokens) or 1
        return {
            t: (tf[t] / total) * self.idf.get(t, 0.0)
            for t in tf
            if self.idf.get(t, 0.0) > 0
        }

    def doc_vector(self, doc_id) -> dict[str, float]:
        for d in self.docs:
            if d["id"] == doc_id:
                return self.vector(d["tokens"])
        return {}

    @staticmethod
    def cosine(a: dict, b: dict) -> float:
        """两个稀疏向量的余弦相似度。"""
        if not a or not b:
            return 0.0
        common = set(a) & set(b)
        dot = sum(a[t] * b[t] for t in common)
        na = math.sqrt(sum(x * x for x in a.values())) or 1.0
        nb = math.sqrt(sum(x * x for x in b.values())) or 1.0
        return dot / (na * nb)

    # -- 用户画像 -----------------------------------------------------------

    def profile(self, interest_terms: list[str],
                feedback_ids: list | None = None,
                feedback_weight: float = 2.0) -> dict[str, float]:
        """
        构建用户画像向量。

        interest_terms：显式兴趣标签（中文词 / 英文词均可）。
        feedback_ids：用户点开/读完过的文章 id（隐式反馈），
                     这些文章的向量会被平均后、以 feedback_weight 权重并入画像。
        """
        if not self._built:
            self.build()
        p: Counter = Counter()
        # 显式兴趣词
        for t in tokenize(" ".join(interest_terms or [])):
            p[t] += 1.0
        # 隐式反馈
        if feedback_ids:
            fv: Counter = Counter()
            for d in self.docs:
                if d["id"] in feedback_ids:
                    for t, w in self.vector(d["tokens"]).items():
                        fv[t] += w
            if fv:
                for t in fv:
                    p[t] += feedback_weight * fv[t] / len(feedback_ids)
        return dict(p)

    # -- 推荐 ---------------------------------------------------------------

    def rank(self, profile: dict, exclude_ids: set | None = None,
             top_k: int = 10, recency_days: int = 0) -> list[tuple[dict, float]]:
        """
        按余弦相似度排序，返回 [(doc, score), ...]。

        recency_days>0 时叠加新鲜度加成：日期越近权重越高（半衰期 = recency_days）。
        """
        if not self._built:
            self.build()
        exclude_ids = exclude_ids or set()
        scored = []
        for d in self.docs:
            if d["id"] in exclude_ids:
                continue
            sim = self.cosine(profile, self.vector(d["tokens"]))
            if sim <= 0:
                continue
            score = sim
            if recency_days > 0:
                score *= self._recency_weight(d["meta"].get("date"), recency_days)
            scored.append((score, d))
        scored.sort(key=lambda x: -x[0])
        return [(d, score) for score, d in scored[:top_k]]

    @staticmethod
    def _recency_weight(date_str, half_life_days: int) -> float:
        if not date_str:
            return 1.0
        try:
            d = datetime.strptime(date_str[:10], "%Y-%m-%d")
        except ValueError:
            return 1.0
        days = (datetime.now() - d).days
        days = max(0, days)
        return 2.0 ** (-days / half_life_days)  # 每过半个半衰期权重减半


# --------------------------------------------------------------------------- #
# 自测：同一个内容池，不同画像得到不同推荐
# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    pool = [
        ("p1", "脑膜瘤 放射治疗 神经外科 肿瘤 复发", {"date": "2026-09-25"}),
        ("p2", "阿尔茨海默病 记忆 认知 衰退 大脑 海马", {"date": "2026-09-28"}),
        ("p3", "央行 降息 货币政策 通胀 经济增长", {"date": "2026-10-01"}),
        ("p4", "A股 上证指数 科技股 半导体 芯片 反弹", {"date": "2026-10-03"}),
        ("p5", "里尔克 诗歌 文学 翻译 散文", {"date": "2026-09-20"}),
        ("p6", "大语言模型 人工智能 神经网络 推理", {"date": "2026-10-05"}),
        ("p7", "衰老 端粒 寿命 抗衰老 长寿", {"date": "2026-09-30"}),
    ]
    r = Recommender()
    for pid, text, meta in pool:
        r.add_document(pid, text, meta)
    r.build()

    users = {
        "脑科学爱好者": ["脑", "神经", "记忆", "认知", "肿瘤", "医学"],
        "财经投资者": ["经济", "金融", "股市", "芯片", "货币", "增长"],
        "文艺青年": ["文学", "诗歌", "散文", "翻译", "历史"],
    }
    for name, interests in users.items():
        prof = r.profile(interests)
        print(f"\n== {name} 的个性化推荐 Top3 ==")
        for doc, score in r.rank(prof, top_k=3):
            print(f"  [{doc['meta'].get('date','?')}] {doc['id']}  相似度={score:.3f}")

# 知荐 (Zhijian)

> 算法推荐取代人工编辑，让「信息找人」。

一个**今日头条式**的个性化内容推荐引擎的最小实现。它不做内容生产，而是把抓来的
内容按每个人的兴趣与行为，算出**千人千面**的个性化排序。

只依赖 Python 3 标准库，零第三方依赖。核心算法约 200 行，一个文件即可读懂。

---

## X 因素：算法推荐取代人工编辑

今日头条（2012）之所以能在 90 天内拉到 1000 万用户，靠的不是内容，而是改变了
「人找信息」的范式：**用算法判断你想看什么，把内容推到你面前**。

「知荐」把这个 X 因素抽出来，做成可运行的最小原型：

```
       传统做法                          知荐的做法
  ┌──────────────────┐          ┌──────────────────┐
  │ 人工编辑定栏目      │          │ 算法算兴趣向量      │
  │ 关键词规则匹配      │    →     │ TF-IDF + 余弦相似度 │
  │ 所有人看到同一份    │          │ 千人千面，各看各的   │
  │ 「人找信息」       │          │ 「信息找人」        │
  └──────────────────┘          └──────────────────┘
```

两者最本质的区别：传统做法是**编辑/规则决定分类**；知荐是**算法根据每个人的
画像与行为，实时算出「这个内容适不适合这个人」**。

---

## 快速开始

```bash
python3 demo.py            # 看千人千面演示（自带真实抓取样本）
python3 recommender.py     # 引擎自测
```

`demo.py` 用同一个 38 篇真实文章池，展示四个画像拿到的**完全不同**的 Top 推荐：

- 🧠 脑科学爱好者 → 大脑/认知/心理学排前面
- 📈 财经投资者 → 经济/金融/市场排前面
- 📚 文艺青年 → 文化/文学/散文排前面
- 🧬 抗衰养生党 → 衰老/长寿/医学排前面

还会演示**隐式反馈**：文艺青年点开两篇衰老文章后，他的画像随之漂移，
推荐排序立刻改变——这正是「信息找人」，用户的行为实时喂养算法。

---

## 原理（content-based recommendation）

```
1. 分词      中文按「二字切分」(bigram)，英文按单词。
             「脑膜瘤的放射治疗」→ [脑膜, 膜瘤, 瘤的, 的放, 放射, 射治, 治疗]

2. IDF      越罕见的词权重越高，过滤掉「的/了/是」这类无信息量的词。

3. 文章向量  TF-IDF：词频 × 逆文档频率。

4. 用户画像  显式兴趣词 + 隐式反馈（点开过的文章向量平均，权重更高）。

5. 推荐      余弦相似度(画像, 文章) + 新鲜度加成 → 排序取 Top-K。
```

整套东西没有魔法，就是一个**把「人」和「文」都向量化、然后算相似度**的过程。
推荐顺序完全由数据算出，没有任何写死的栏目。

---

## 目录结构

```
zhijian/
├── recommender.py            # 核心：TF-IDF + 余弦相似度推荐引擎
├── fetcher.py                # 内容聚合：river.to / PubMed / RSS，归一化输出
├── store.py                  # SQLite：articles / users / feedback 三张表
├── pipeline.py               # 编排：抓取 → 入库 → 推荐 → 反馈（命令行入口）
├── demo.py                   # 千人千面 + 隐式反馈 演示（自带样本）
├── config.example.json       # 配置模板（数据源 / 数据库）
├── data/
│   ├── sample_articles.json  # 38 篇真实抓取样本（demo 用）
│   └── zhijian.db            # SQLite 库（fetch 后生成，不入库）
├── README.md
└── LICENSE
```

---

## 阶段 1+2：接上真实数据（聚合 + 存储 + 推荐）

```bash
cp config.example.json config.json   # 填 river.login_url（wtlwp_token 登录链接）
python3 pipeline.py fetch            # 抓取 river.to + PubMed + RSS，写入 SQLite

python3 pipeline.py add-user u_brain 脑科学爱好者 "心理学,大脑,神经,记忆,认知"
python3 pipeline.py add-user u_finance 财经投资者 "经济,金融,股市,市场,货币"
python3 pipeline.py recommend u_brain 10        # 千人千面：同一内容池，各看各的

python3 pipeline.py feedback u_brain <article_id> read    # 记隐式反馈 → 画像漂移
python3 pipeline.py recommend u_brain 10                  # 再推荐，排序已变
python3 pipeline.py stats                                # 库统计
```

`fetch` 是「尽力而为」：某个来源失败（比如 river 令牌过期、某站 RSS 403）不会
拖垮整次抓取，会打印警告并继续。PubMed 抓取内置 0.4 秒间隔，遵守 NCBI 限流建议。

实测（真实数据，120 篇入库）：

- 脑科学爱好者 → 用光控制大脑 / 有望改写物理学的磁体 / …
- 抗衰养生党 → 脑膜瘤放疗 / BMJ 医学前沿 / …
- 隐式反馈：脑科学爱好者点开 3 篇医学论文后，推荐立刻从「脑科学」转向「医学」，
  这正是「信息找人」——用户行为实时喂养算法。

## 从「原型」到「完整产品」的路线图

这个仓库是**大脑**，完整产品还需要把「手脚」接上：

| 阶段 | 内容 | 状态 |
| --- | --- | --- |
| 0. 推荐引擎 | TF-IDF + 余弦相似度 + 画像 + 隐式反馈 | ✅ 本仓库 |
| 1. 内容聚合 | 抓取 river.to / PubMed / Nature / RSS，归一化入库 | ✅ 已接 |
| 2. 存储 | SQLite：`articles` / `users` / `feedback` 三张表 | ✅ 已接 |
| 3. 多用户 | 每个用户一份画像，一人一个个性化 digest | 🔧 待接 |
| 4. 推送 | 按用户时区/频率，邮件或 Webhook 推送 | 🔧 待接 |
| 5. Web 界面 | 注册、选兴趣、点「喜欢/不感兴趣」回收反馈 | 🔜 |
| 6. 升级算法 | 换 word2vec/协同过滤/召回排序两段式 | 🔜 |

---

## 推送到你的 GitHub

`gh` CLI 未安装，所以手动执行（把 `Ericnotme` 换成你的用户名、`zhijian` 换成仓库名）：

```bash
cd zhijian
git init
git add .
git commit -m "init: 知荐 — 今日头条式个性化推荐引擎"
git branch -M main
git remote add origin https://github.com/Ericnotme/zhijian.git
git push -u origin main
```

> ⚠️ 请先到 github.com 手动建一个空仓库 `zhijian`（不要勾选 README/license，否则要 rebase）。

---

## 许可

MIT License —— 见 [LICENSE](LICENSE)。

## 免责

`data/sample_articles.json` 是演示用的文章标题与摘要片段，版权归原作者与出版方所有，
仅供学习算法之用，请勿商用。

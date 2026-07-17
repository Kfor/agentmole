# Agentmole 数据契约 v3

> v3.3 追加（owner 2026-07-07）：顶层新增 `report_title`（可选，agent 生成）——报告页大标题，每人一句、用户语言、**以「聊天记录 / chat log」为重点词**（模板自动高亮该词）；缺失时模板回退到固定默认标题（同样把重点放在 chat log 上）。

> v3.2 变更（owner 反馈 2026-07-06 深夜，`schema_version` 仍为 3——均为展示层/可选）：
> - 顶层 `lang`（`"zh"`|`"en"`，缺省 `"zh"`；scan.py 已按语料 CJK 占比自动判定）：
>   **模板界面语言（chrome）跟随此字段**——区块标题、按钮、小字、tooltip、对话框、
>   榜单/对比文案等全部查模板内 `I18N = {zh, en}` 字典渲染；数据内容（narrative 等）
>   本就由 agent 按用户语言书写，不受影响。
> - 模板消费两个对比端点的新形态（端点契约见文末「发布 API 契约」）：
>   `/api/percentile` 返回 `{insufficient, total}` 时显示「样本还不够（当前 N 份）」；
>   排名正常返回后**同一次点击授权内**追加请求 `GET /api/archetype-stats`，
>   渲染「你是全网 X% 的『原型名』」身份行（X = dist 中匹配 `archetype.id` 条目的
>   `pct`；找不到则不显示）。所有对比结果区常驻小字：
>   「该结果仅限本产品用户中的比较结果」。
> - 模板出网点由两个变为三个（archetype-stats），仍全部集中声明在 `<head>`
>   信任面注释块、同源拼接、仅用户点击可触发。

> v3 变更（owner 反馈 2026-07-06 晚）：**发挥层扩容并前置**。
> - 新增三个 agent 创作字段（deep 模式填写，fast 为 null/[]）：
>   - `narrative`：`{"paragraphs": ["..."]}`——「你是怎么和 AI 协作的」解读，2–4 段，
>     从委托方式/信任半径/验收习惯/协作弧线角度写，是整份报告的灵魂段落
>   - `moments`：`[{"ts","title","text","quote"}]`——年度名场面 3–6 个（quote 逐字）
>   - `diagnosis`：`[{"issue","evidence","cost","fix_hint"}]`——隐性问题诊断 2–4 条
> - **报告区块顺序改为**：原型 → 协作解读(narrative) → 金句/Roast → 年度名场面(moments)
>   → 品味信条 → 硬核数字 → 阵营对比 → 词云 → 磨合曲线 → 热力图 → 徽章
>   → 隐性问题(diagnosis) → skill 蒸馏。创作内容整体前置。
> - 硬核数字区必须展示输入侧：`fresh_in_tokens` 与 `cache_read_tokens` 独立卡片；
>   token 区常驻小字注明「Claude Code 默认只保留 ~30 天全保真记录，历史数据存在偏差/丢失」
>   （无论是否显示估算值）。
> - 定位变更：产品主叙事 = **「了解你是如何与 AI 协作的」**；「历史蒸发」降级为
>   次要的信任/效用点，不再作为第一钩子。
> - `stats` 再新增（owner 头脑风暴轮，全部可选）：
>   `usage_split`（写码/设计/调研/管理/其他消息占比，关键词启发式）、
>   `api_cost_estimated_usd` + `api_cost_note`（等值 API 成本，按公开牌价分项计价）、
>   `parallel_peak_projects_hour`（单小时并行项目峰值）、`interruptions`（打断 agent 次数）、
>   `weekend_share`（周末消息占比）、`sidechain_share`（subagent 调用占比，"二级外包率"）、
>   `project_top`（top5 项目占比；v3 模板暂不渲染，隐私由用户把关）
> - v3.1 追加（owner 反馈，均为可选创作字段）：
>   - `stats_highlights`：`[{"value","label","quip"}]` 3–5 个——**agent 为这个用户亲自挑选**的
>     最炸裂数字（不同人的爆点完全不同），带定制吐槽短语；模板渲染为原型卡之后的
>     「关键数字带」（紧凑、移动端首屏可见）。缺失时模板自动挑产出/成本/连跑兜底。
>   - `persona_guess`：`{"guesses":[{"guess","why","confidence"}],"note"}`——「我猜猜你是谁」，
>     agent 从协作史推理主人画像（作息/职业阶段/性格/审美倾向…），3–6 条，戏谑但有依据；
>     放报告**靠后**位置（诊断之后、skill 蒸馏之前）；`portrait` 形象图若存在，与本区合并展示。
>   - `stats.effort_split`：Codex effort 档位分布（rollout 计数，机器算）。
>   - 效率倍数（模板机算，口径注释在码）：产出词数 ÷（40wpm×8h×活跃天）≈「相当于 N 个
>     前 AI 时代全职打字工程师」。
> - `schema_version: 3`（服务端接受 1/2/3）。

> v2 变更（相对 v1，全部为可选新增字段，模板必须兼容 v1 数据）：
> - `stats` 新增：`session_turns_avg`（人类消息数/有输入的 session 数）、`skills_installed`、
>   `agent_out_tokens_estimated` + `estimation_note`（Claude transcript 蒸发期外推口径，报告主显时必须带「估算」标注）
> - 顶层新增 `per_source`：分 agent 的使用对比（`{human_msgs, sessions, out_tokens, active_days, share, roast}`），
>   `roast` 为该 agent 对用户的一句吐槽（深挖模式填写，可 null）
> - 顶层新增 `theme`：主题 id（见 `docs/themes.json`）。v2.0 起报告只有单一主题 `brutalist`（Neo-brutalism），此字段留空即可，仅为兼容保留
> - 顶层新增 `portrait`（可选）：`data:image/...;base64` 形象图，由用户自己的 harness 本地生成（如 Codex 内置画图）；模板只接受 data: URI，绝不外链加载
> - 服务端新增 `GET /api/percentile?axis=<榜单轴>&value=<数字>` → `{total, beaten, pct}`；
>   只接收白名单轴的单个数字，必须由用户点击触发
> - 发布 API 增加 IP 滑窗限流（5/时、20/天），超限 429

skill 产出、报告模板消费、榜单聚合的唯一接口。三方（skill.md / template.html / site Worker）都以本文档为准；改字段必须升 `schema_version` 并保持榜单只消费声明字段（PRD §6.2）。

## 载体

报告 HTML 内嵌一个 script 块：

```html
<script id="agentmole-data" type="application/json">{ ... }</script>
```

- 发布 API 从上传的 HTML 里解析这个块做榜单聚合（页面本体原样存储，WYSIWYG）。
- 模板 JS 启动时读取同一块渲染全部区块。
- **注入前 agent 已审阅敏感内容**（不做代码正则脱敏；agent 凭判断改写/移除密钥、真实姓名、未发布项目名等；分享时页面也提示用户可让 agent 改任何内容）。

## 顶层结构

```jsonc
{
  "schema_version": 1,
  "generated_at": "2026-07-06T12:00:00Z",   // ISO8601 UTC
  "handle": null,                            // 用户展示名；发布时可为 null（匿名鼹鼠）
  "sources": ["claude_code", "codex"],      // 实际扫到数据的 harness
  "period": { "from": "2025-08-01", "to": "2026-07-06" },
  "mode": "deep",                            // "fast"（纯统计）| "deep"（并行挖掘）

  "stats": { ... },                          // §stats — 纯数字，全部可机器复算
  "archetype": { ... },                      // §archetype — 人格原型
  "quotes": { ... },                         // §quotes — 金句 + roast
  "wordcloud": { ... },                      // §wordcloud
  "taming_curve": [ ... ],                   // §taming_curve — 磨合曲线
  "badges": [ ... ],                         // §badges
  "creeds": [ ... ],                         // §creeds — 品味信条
  "distilled_skills": [ ... ]                // §distilled_skills — skill 蒸馏区
}
```

`stats` 之外的区块在 `fast` 模式下可为 `null` / `[]`，模板必须优雅降级（隐藏区块）。

## stats（榜单只消费这里的字段）

```jsonc
{
  "sessions": 4300,
  "active_days": 214,
  "human_msgs": 16405,
  "agent_out_tokens": 981000000,     // main + sidechain 输出合计
  "fresh_in_tokens": 12300000,
  "cache_read_tokens": 22100000000,
  "cache_hit_rate": 0.94,            // cache_read / (cache_read + fresh_in)
  "api_calls": 412000,
  "leverage_ratio": 59800,           // agent_out_tokens / human 输入 token 估算（书面定义见 skill）
  "longest_streak_days": 41,
  "night_owl_index": 0.31,           // 00:00–06:00 本地时区人类消息占比
  "correction_rate": 0.043,          // 纠偏消息 / human_msgs（分类口径见 skill）
  "rules_taught": 87,                // 用户沉淀的持久规则数（CLAUDE.md/AGENTS.md 行数等，口径见 skill）
  "hour_histogram": [0,0,3, ...],    // 24 项，本地时区
  "weekday_histogram": [120, ...],   // 7 项，周一起
  "daily_activity": { "2026-07-01": 5 },  // 热力图；键=本地日期，值=human msgs
  "monthly": [ { "month": "2026-06", "human_msgs": 1200, "out_tokens": 3.1e8, "sessions": 210 } ],
  "models": { "claude-opus-4-6": 210000 },      // model → api calls
  "camp": "dual"                     // "claude" | "codex" | "dual"（阵营梗）
}
```

## archetype

```jsonc
{
  "id": "root-cause-tyrant",         // 12–16 个原型的稳定 id（清单见 skill.md 原型表）
  "name": "根因主义暴君",
  "name_en": "The Root-Cause Tyrant",
  "tagline": "一句话人设描述",
  "dimensions": {                    // 全部从真实数据算出，0–1
    "automation_leverage": 0.92,
    "correction_density": 0.31,
    "night_shift": 0.28,
    "msg_length": 0.55,
    "politeness": 0.12,
    "taste_signal_density": 0.77
  }
}
```

## quotes

```jsonc
{
  "harshest": { "text": "原句（已脱敏）", "ts": "2026-03-02", "context": "一句话场景" },
  "signature": [ { "text": "...", "count": 347 } ],   // 口头禅 top N（带次数）
  "roast": "AI 反向吐槽段落（基于真实统计，不编造）"
}
```

## wordcloud

```jsonc
{ "words": [ { "text": "咋样了", "weight": 347 } ] }   // top ~80，已去停用词
```

## taming_curve

```jsonc
[ { "month": "2026-06", "correction_rate": 0.031, "rules_cumulative": 87 } ]
```

## badges

```jsonc
[ { "id": "same-msg-x6", "name": "复读机", "desc": "同一句话连发 6 次", "evidence": "已脱敏原文/数字" } ]
```

## creeds

```jsonc
[ { "creed": "十条工程信条之一", "evidence": { "text": "原文引用（已脱敏）", "ts": "2026-01-12" } } ]
```

## distilled_skills

```jsonc
[ {
  "title": "skill 草稿名",
  "kind": "skill",                       // "skill" | "claude-md-patch"
  "trigger": "何时激活这条",
  "stop": "何时算完成 / 成功",            // v3.1 新增，可选
  "body": "完整 markdown 正文（参数化，一键复制）",
  "reuse": { "seen": 42, "invariance": "high", "portability": "med" }, // v3.1 新增，可选：排序信号，非 gate
  "evidence": [ { "quote": "逐字原文", "ts": "..." } ],                 // v3.1 新增，可选
  "from": "workflow"                     // v3.1 新增，可选：出处信号类 workflow|correction|pattern|standard_move|tooling_gap
} ]
// v3.1 起模板按 reuse 排序（最可复用在前）并把 seen 作为估算露出；旧数据缺这些字段仍正常渲染（向后兼容）。
```

## 发布 API 契约（site Worker）

- `POST /api/publish`，body = 完整 HTML 文本（`text/html`），CORS 放行 `null` origin（本地 file:// 页面）。
- Worker 校验：体积上限（2 MB）、能解析出 `#agentmole-data` 且 `schema_version` 已知、stats 数字字段类型正确。
- 返回 `{ "url": "https://<域名>/u/<slug>", "slug": "..." }`；slug = 随机 8 字符 base36，不可枚举。
- 重复发布：v1 直接生成新 slug（无账号体系，PRD §7）。
- 榜单只读取解析出的 `stats` 白名单字段 + `archetype.id` + `camp`，写入榜单存储；页面 HTML 原样存储原样回放（加 CSP 头，见 site 实现）。
- `GET /api/percentile?axis=<榜单轴>&value=<数字>`：对应轴非空样本 `total < 30`（`MIN_SAMPLE`，owner 决策：数据少时不上线对比数字）时返回 HTTP 200 `{"insufficient": true, "total": <n>}`，模板端显示「样本还不够（当前 N 份），等鼹鼠多起来再比」（v3.2 起，不再按失败态隐藏）；样本足够时返回 `{axis, label, total, beaten, pct}`。
- `GET /api/archetype-stats`：原型稀有度分布，返回 `{total, dist: [{archetype_id, archetype_name, n, pct}]}`（按 `n` 降序，`pct` 一位小数）；同受 `MIN_SAMPLE` 门槛，样本不足时返回 HTTP 200 `{"insufficient": true, "total": <n>}`。CORS 同 percentile（GET 简单请求，ACAO `*`）。

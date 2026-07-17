#!/usr/bin/env python3
"""Agentmole scanner — 本地扫描你与 AI 的协作历史，产出统计 JSON。

信任声明（请审查）：
  - 本文件从头到尾没有任何网络访问代码（无 socket / urllib / requests / subprocess 出网）。
  - 只读取：~/.claude/projects/**（transcripts）、~/.claude/history.jsonl、
            ~/.codex/sessions/**（rollouts）、~/.codex/history.jsonl、
            ~/.openclaw/agents/*/sessions/**、
            ~/Library/Application Support/Cursor/User/**（state.vscdb，SQLite 以 mode=ro 只读打开）、
            ~/.claude/CLAUDE.md、~/.codex/AGENTS.md、~/.claude/skills、~/.claude/commands、~/.codex/prompts
  - 只写入：--workdir 指定的工作目录（默认 ~/.agentmole/work/）。
  - 依赖：Python 3.9+ 标准库（含 sqlite3，仅只读连接），无第三方包。

用法：
  python3 scan.py scan [--workdir DIR]     # 全量扫描 → report-data.json + 语料分片

口径说明（报告里引用的数字如何得来，全部可复算）：
  - token 总口径      = **API 上报的计费用量标记**，不是文本长度估算：Claude transcript 逐条
                        assistant 消息的 usage 字段（input + output + cache_read + cache_creation）
                        + Codex rollout 的 token_count 事件（session 累积快照，取每个 session 的
                        末值；与 Codex 自身账本库 state_5.sqlite 的 threads.tokens_used 数值一致，
                        可互为交叉核对）。该口径天然包含 cache 重读与 thinking/reasoning token
                        （计费在 output 内）——文本长度估算会漏掉这两块，对重度 agent 工作流可
                        低估几个数量级。两条防重/防漏纪律（本脚本已内置）：① 同一条回复会按
                        content block 拆成多行、usage 原样复写——必须按 message.id 去重，
                        逐行直加会虚增约 2 倍；② subagent transcript 存在
                        <project>/<session>/subagents/ 子目录，是真实计费，浅层 glob 会漏掉。
  - human_msgs        = 你亲手输入的消息条数（Claude transcripts 人类消息 + Codex history
                        + OpenClaw user 消息 + Cursor 用户气泡）
  - cursor 时间戳口径 = 新版气泡自带逐条 createdAt；旧版气泡没有逐条时间戳（Cursor 存储硬伤），
                        用所属 composer.createdAt / 旧版 tab.lastSendTime 近似
  - sessions（cursor）= composer 数 + 旧版 aichat tab 数
  - agent_out_tokens  = 主线程 + subagent 输出 token 合计
  - cache_hit_rate    = cache_read / (cache_read + fresh_in)
  - leverage_ratio    = agent_out_tokens / (你输入的总字符数 / 3)   # 字符/3 ≈ 混合中英 token 估算
  - night_owl_index   = 本地时区 00:00–05:59 的人类消息占比
  - correction_rate   = 命中纠偏模式的消息占比（启发式关键词，v1 口径）
  - rules_taught      = ~/.claude/CLAUDE.md + ~/.codex/AGENTS.md + ~/.claude/projects/*/memory/*.md 非空内容行数
  - taming_curve.rules_cumulative = 累计出现的品味/流程声明消息数（启发式）
  - agent_out_tokens_estimated    = Claude transcript 蒸发期外推估算（窗口内平均每消息产出 ×
                                    全史打字消息数 + Codex 实测）；estimation_note 记口径
  - session_turns_avg             = 人类消息总数 / 有人类输入的 session 数
  - skills_installed              = ~/.claude/skills/*/ + ~/.claude/commands/*.md + ~/.codex/prompts/*.md 计数
"""
import json, os, sys, glob, re, sqlite3
from collections import defaultdict, Counter
from datetime import datetime, timezone

SCHEMA_VERSION = 3

# 已确认存在但尚未支持解析的 harness（探测到会在摘要中提示，配方接入后移入正式扫描）。
# 考古结论（2026-07-06）：opencode 本机数据是单日批量实验（1.2 万 session 同日同目录），
# 并入会污染作息/消息口径故不接；gemini/qwen 数据量为零；Manus 云端无本地数据不可接。
# antigravity 考古结论（2026-07-07）：会话正文 ~/.gemini/antigravity/conversations/*.pb
# 整文件加密（字节熵 ≈8.0 bit/Byte、无任何压缩魔数，Chromium safeStorage 类方案，密钥在
# 系统钥匙串），stdlib 无法解析；唯一明文是 globalStorage state.vscdb 里 base64-protobuf 的
# agentManagerInitState——只有会话级元数据（UUID/标题/秒级时间戳/计数器），没有用户消息
# 文本、没有 token 用量 → 进不了语料与 token 口径，保留探测，待其改明文或提供官方导出。
HARNESS_PROBES = {
    "antigravity": "~/.gemini/antigravity/conversations",
    "gemini_cli": "~/.gemini",
    "opencode": "~/.local/share/opencode",
    "qwen_code": "~/.qwen",
}

OPENCLAW_AGENTS = os.path.expanduser("~/.openclaw/agents")

CLAUDE_PROJECTS = os.path.expanduser("~/.claude/projects")
CLAUDE_HISTORY = os.path.expanduser("~/.claude/history.jsonl")
CODEX_SESSIONS = os.path.expanduser("~/.codex/sessions")
CODEX_HISTORY = os.path.expanduser("~/.codex/history.jsonl")
RULE_FILES = [os.path.expanduser("~/.claude/CLAUDE.md"), os.path.expanduser("~/.codex/AGENTS.md")]

SKIP_PREFIXES = ("<command-name>", "<local-command-caveat>", "<local-command-stdout",
                 "<system-reminder>", "[Request interrupted", "<task-notification>")

# ---------- 启发式模式（v1 口径，报告页脚注明是启发式） ----------
RE_CORRECTION = re.compile(
    r"^(不对|不是这|不是的|不行|别这|错了|又错|等等|停|你没|你怎么|回滚|撤销|重来|改回)"
    r"|^(no[,.\s]|wrong|stop|don't|undo|revert|that'?s not|not what i)"
    r"|怎么又|还是错|还是不对|你又|并没有|没解决|没修好|白改|改坏|又坏", re.I)
RE_POLITE = re.compile(r"请|麻烦|谢谢|辛苦|拜托|please|thank", re.I)
RE_TASTE = re.compile(
    r"不应该|永远|从不|必须|禁止|原则|规范|风格|我喜欢|我讨厌|以后都|每次都|记住|以后不要"
    r"|always|never|must|prefer|convention|principle|from now on|rule of thumb", re.I)

# 用途分类（v1 启发式：关键词投票取最高，报告脚注注明口径）
USAGE_BUCKETS = [
    ("design", re.compile(r"设计|样式|配色|字体|排版|美观|好看|太丑|视觉|动效|布局|画一|画个|图标|素材|封面|海报"
                          r"|logo|icon|ui|ux|css|hero|banner|mockup|figma", re.I)),
    ("coding", re.compile(r"代码|函数|报错|编译|测试|重构|实现|接口|数据库|部署|类型|依赖|脚本|修复|回滚"
                          r"|bug|crash|error|fix|npm|python|git|commit|api|log|diff|lint|typescript|refactor", re.I)),
    ("research", re.compile(r"调研|搜索|查一下|查查|了解一下|对比|竞品|资料|分析一下|原理|方案比较|市场"
                            r"|research|survey|benchmark", re.I)),
    ("management", re.compile(r"咋样了|进度|状态|情况如何|继续|推进|监控|盯着|验收|安排|排期|优先级|汇报"
                              r"|status|progress", re.I)),
]

def usage_split(corpus):
    counts = Counter()
    for r in corpus:
        t = r["text"][:400]
        votes = {name: len(pat.findall(t)) for name, pat in USAGE_BUCKETS}
        best = max(votes, key=votes.get)
        counts[best if votes[best] > 0 else "other"] += 1
    n = max(1, len(corpus))
    return {k: round(counts.get(k, 0) / n, 4) for k in ("coding", "design", "research", "management", "other")}

# 等值 API 成本（美元/百万 token，公开牌价近似；口径=如果全按 API 计价）
PRICE_TABLE = [  # (模型名子串, in, out, cache_read)
    ("opus", 15.0, 75.0, 1.5),
    ("sonnet", 3.0, 15.0, 0.3),
    ("haiku", 0.8, 4.0, 0.08),
    ("fable", 20.0, 100.0, 2.0),
    ("gpt", 1.25, 10.0, 0.125),
    ("", 3.0, 15.0, 0.3),  # 兜底
]

def price_of(model):
    m = (model or "").lower()
    for key, i, o, c in PRICE_TABLE:
        if key in m:
            return i, o, c
    return PRICE_TABLE[-1][1:]

# 脱敏不在代码里做（owner 2026-07-07 决策）：不再做 [REDACTED] 那套正则替换。
# 敏感内容的判断交给 agent——它在 skill.md Step 5 里逐字段审阅报告数据，凭理解决定
# 什么该改（比正则聪明，且不把邮箱/路径/姓名一律打码搞脏页面）。分享时页面也会提示
# 用户：想改任何内容，直接对 agent 说。

# ---------- 工具 ----------
def text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(c.get("text", "") for c in content
                         if isinstance(c, dict) and c.get("type") == "text")
    return ""

def to_local(ts_iso):
    try:
        return datetime.fromisoformat(ts_iso.replace("Z", "+00:00")).astimezone()
    except Exception:
        return None

def log(msg):
    print(msg, file=sys.stderr)

# ---------- Claude Code 扫描（源自已验证的试点脚本） ----------
def scan_claude():
    sessions, corpus = [], []
    if not os.path.isdir(CLAUDE_PROJECTS):
        return sessions, corpus
    files = glob.glob(os.path.join(CLAUDE_PROJECTS, "*", "*.jsonl"))
    # 新版把 subagent transcript 存在 <proj>/<session>/subagents/ 下——token 是真实用量必须计入；
    # 文件内自带 isSidechain 标记，走同一套解析即可，只是不计为独立 session
    sub_files = glob.glob(os.path.join(CLAUDE_PROJECTS, "*", "*", "subagents", "*.jsonl"))
    files = files + sub_files
    log(f"[claude] scanning {len(files)} session files (incl. {len(sub_files)} subagent transcripts)")
    for i, path in enumerate(files):
        if i % 500 == 0 and i:
            log(f"  {i}/{len(files)}")
        is_subagent = os.sep + "subagents" + os.sep in path
        rel = os.path.relpath(path, CLAUDE_PROJECTS)
        proj = rel.split(os.sep)[0]
        s = {"first_ts": None, "last_ts": None, "human_msgs": 0, "assistant_calls": 0,
             "in_tok": 0, "out_tok": 0, "cache_read": 0,
             "side_in_tok": 0, "side_out_tok": 0, "side_cache_read": 0, "sidechain_calls": 0,
             "interruptions": 0, "models": Counter()}
        seen = set()
        try:
            with open(path, "r", errors="replace") as f:
                for line in f:
                    if len(line) < 10:
                        continue
                    try:
                        d = json.loads(line)
                    except Exception:
                        continue
                    ts = d.get("timestamp")
                    if ts:
                        if s["first_ts"] is None or ts < s["first_ts"]:
                            s["first_ts"] = ts
                        if s["last_ts"] is None or ts > s["last_ts"]:
                            s["last_ts"] = ts
                    t = d.get("type")
                    if t == "user":
                        if d.get("isMeta") or d.get("isSidechain") or is_subagent:
                            continue
                        msg = d.get("message", {})
                        txt = text_of(msg.get("content"))
                        if not txt or txt.startswith(SKIP_PREFIXES):
                            if txt.startswith("[Request interrupted"):
                                s["interruptions"] += 1  # 你打断 agent 的次数
                            continue
                        origin = d.get("origin", {})
                        kind = origin.get("kind") if isinstance(origin, dict) else None
                        is_human = (kind == "human") or (d.get("promptSource") == "typed")
                        if kind is None and d.get("promptSource") is None:
                            content = msg.get("content")
                            if isinstance(content, list) and any(
                                    isinstance(c, dict) and c.get("type") == "tool_result" for c in content):
                                continue
                            is_human = True
                        if is_human:
                            s["human_msgs"] += 1
                            corpus.append({"src": "claude", "ts": ts, "project": proj, "text": txt[:8000]})
                    elif t == "assistant":
                        msg = d.get("message", {})
                        usage = msg.get("usage")
                        mid = msg.get("id") or d.get("requestId") or d.get("uuid")
                        if not usage or mid in seen:
                            continue
                        seen.add(mid)
                        itok = (usage.get("input_tokens") or 0) + (usage.get("cache_creation_input_tokens") or 0)
                        otok = usage.get("output_tokens") or 0
                        cr = usage.get("cache_read_input_tokens") or 0
                        if d.get("isSidechain"):
                            s["sidechain_calls"] += 1
                            s["side_in_tok"] += itok
                            s["side_out_tok"] += otok
                            s["side_cache_read"] += cr
                        else:
                            s["assistant_calls"] += 1
                            s["in_tok"] += itok
                            s["out_tok"] += otok
                            s["cache_read"] += cr
                        if msg.get("model"):
                            s["models"][msg["model"]] += 1
        except Exception as e:
            log(f"ERR {path}: {e}")
            continue
        if s["human_msgs"] or s["assistant_calls"] or s["sidechain_calls"]:
            s["models"] = dict(s["models"])
            s["is_subagent"] = is_subagent
            if is_subagent:
                # subagent 文件里的 assistant 行有的没带 isSidechain 标——统一归入 side 口径
                s["sidechain_calls"] += s["assistant_calls"]
                s["side_in_tok"] += s["in_tok"]
                s["side_out_tok"] += s["out_tok"]
                s["side_cache_read"] += s["cache_read"]
                s["assistant_calls"] = 0
                s["in_tok"] = s["out_tok"] = s["cache_read"] = 0
                s["human_msgs"] = 0
            sessions.append(s)
    return sessions, corpus

# ---------- Codex 扫描（流式 + 子串预过滤，源自试点脚本） ----------
def scan_codex():
    sessions = []
    if not os.path.isdir(CODEX_SESSIONS):
        return sessions
    files = sorted(glob.glob(os.path.join(CODEX_SESSIONS, "*", "*", "*", "rollout-*.jsonl")))
    log(f"[codex] scanning {len(files)} rollout files")
    for i, path in enumerate(files):
        if i % 1000 == 0 and i:
            log(f"  {i}/{len(files)}")
        rec = {"session_id": None, "originator": None, "cwd": None, "model": None, "effort": None,
               "first_ts": None, "last_ts": None, "user_msgs": 0,
               "in_tok": 0, "cached_tok": 0, "out_tok": 0, "turns": 0}
        last_total = None
        try:
            with open(path, "r", errors="replace") as f:
                for line in f:
                    if not ('"session_meta"' in line or '"token_count"' in line
                            or '"user_message"' in line or '"turn_context"' in line
                            or '"task_started"' in line):
                        continue
                    try:
                        d = json.loads(line)
                    except Exception:
                        continue
                    ts = d.get("timestamp")
                    if ts:
                        if rec["first_ts"] is None:
                            rec["first_ts"] = ts
                        rec["last_ts"] = ts
                    t, p = d.get("type"), d.get("payload", {})
                    if t == "session_meta":
                        rec["session_id"] = p.get("session_id") or p.get("id")
                        rec["originator"] = p.get("originator")
                        rec["cwd"] = p.get("cwd")
                    elif t == "turn_context" and rec["model"] is None:
                        rec["model"] = p.get("model")
                        rec["effort"] = p.get("effort")
                    elif t == "event_msg":
                        pt = p.get("type")
                        if pt == "token_count":
                            tot = (p.get("info") or {}).get("total_token_usage")
                            if tot:
                                last_total = tot
                        elif pt == "user_message":
                            rec["user_msgs"] += 1
                        elif pt == "task_started":
                            rec["turns"] += 1
        except Exception as e:
            log(f"ERR {path}: {e}")
            continue
        if last_total:
            rec["in_tok"] = last_total.get("input_tokens", 0) or 0
            rec["cached_tok"] = last_total.get("cached_input_tokens", 0) or 0
            rec["out_tok"] = last_total.get("output_tokens", 0) or 0
        sessions.append(rec)
    return sessions

def claude_history_corpus(existing_corpus):
    """补上已被 30 天清理蒸发的历史：~/.claude/history.jsonl 保存全部打字记录。
    与 transcript 语料按（分钟桶 + 文本前 50 字）去重，只补缺失的行。"""
    rows = []
    if not os.path.exists(CLAUDE_HISTORY):
        return rows
    seen = set()
    for r in existing_corpus:
        dt = to_local(r["ts"])
        if dt:
            seen.add((dt.strftime("%Y-%m-%d %H:%M"), r["text"][:50]))
    for l in open(CLAUDE_HISTORY, errors="replace"):
        try:
            d = json.loads(l)
        except Exception:
            continue
        t = (d.get("display") or "").strip()
        if not t or t.startswith("/"):
            continue
        dt = datetime.fromtimestamp(d["timestamp"] / 1000, tz=timezone.utc)
        key = (dt.astimezone().strftime("%Y-%m-%d %H:%M"), t[:50])
        if key in seen:
            continue
        seen.add(key)
        proj = os.path.basename(d.get("project") or "?") or "?"
        rows.append({"src": "claude", "ts": dt.isoformat(), "project": proj, "text": t[:8000]})
    return rows

# ---------- OpenClaw 扫描 ----------
RE_OC_META = re.compile(r"^(Conversation info|Sender) \(untrusted metadata\):")
# OpenClaw 会把自动化触发（heartbeat/cron/会话管理）伪装成 user 消息——实测占 7 成，
# 必须剔除，否则用户会"被说了"上千句话
OC_AUTOMATION_PREFIXES = (
    "Read HEARTBEAT.md", "A new session was started via", "Pre-compaction memory flush",
    "[cron:", "[Queued messages", "reply exactly:", "Continue where you left off",
)
RE_OC_TS_PREFIX = re.compile(r"^\[[A-Z][a-z]{2} \d{4}-\d{2}-\d{2} [\d:]+ GMT[+\-]\d+\]\s*")

def _openclaw_user_text(txt):
    """剥掉 openclaw user 消息的外壳：IM 元数据包裹 / 媒体占位 / System 注入 / 自动化触发。"""
    if txt.startswith("[media attached") or txt.startswith("System:"):
        return ""
    if txt.startswith(OC_AUTOMATION_PREFIXES):
        return ""
    if RE_OC_META.match(txt):  # IM 渠道消息：真实文本在最后一个 ``` 围栏后
        txt = txt.rsplit("```", 1)[-1]
        txt = "\n".join(l for l in txt.splitlines() if l and not l.startswith("[message_id"))
    txt = RE_OC_TS_PREFIX.sub("", txt.strip())  # 去掉 IM 转发的时间戳前缀
    if txt.startswith(OC_AUTOMATION_PREFIXES):
        return ""
    return txt.strip()

def scan_openclaw():
    sessions, corpus = [], []
    if not os.path.isdir(OPENCLAW_AGENTS):
        return sessions, corpus
    files = glob.glob(os.path.join(OPENCLAW_AGENTS, "*", "sessions", "*.jsonl*"))
    log(f"[openclaw] scanning {len(files)} session files")
    for path in files:
        agent = path.split(os.sep)[-3]
        s = {"first_ts": None, "last_ts": None, "human_msgs": 0, "assistant_calls": 0,
             "in_tok": 0, "out_tok": 0, "cache_read": 0, "models": Counter()}
        try:
            with open(path, errors="replace") as f:
                for line in f:
                    try:
                        d = json.loads(line)
                    except Exception:
                        continue
                    if d.get("type") != "message":
                        continue
                    ts = d.get("timestamp")
                    if ts:
                        if s["first_ts"] is None:
                            s["first_ts"] = ts
                        s["last_ts"] = ts
                    m = d.get("message", {})
                    if m.get("role") == "user":
                        txt = _openclaw_user_text(text_of(m.get("content")))
                        if txt:
                            s["human_msgs"] += 1
                            corpus.append({"src": "openclaw", "ts": ts,
                                           "project": agent, "text": txt[:8000]})
                    elif m.get("role") == "assistant":
                        u = m.get("usage") or {}
                        if u:
                            s["assistant_calls"] += 1
                            s["in_tok"] += (u.get("input") or 0) + (u.get("cacheWrite") or 0)
                            s["out_tok"] += u.get("output") or 0
                            s["cache_read"] += u.get("cacheRead") or 0
                        if m.get("model"):
                            s["models"][m["model"]] += 1
        except Exception as e:
            log(f"ERR {path}: {e}")
            continue
        if s["human_msgs"] or s["assistant_calls"]:
            s["models"] = dict(s["models"])
            sessions.append(s)
    return sessions, corpus

def codex_corpus(codex_sessions):
    rows = []
    if not os.path.exists(CODEX_HISTORY):
        return rows
    cwd_of = {s["session_id"]: s["cwd"] for s in codex_sessions if s.get("session_id") and s.get("cwd")}
    for l in open(CODEX_HISTORY, errors="replace"):
        try:
            d = json.loads(l)
        except Exception:
            continue
        t = (d.get("text") or "").strip()
        if not t or t.startswith("/"):
            continue
        ts = datetime.fromtimestamp(d["ts"], tz=timezone.utc).isoformat()
        cwd = cwd_of.get(d.get("session_id"), "?")
        rows.append({"src": "codex", "ts": ts, "project": os.path.basename(cwd) if cwd != "?" else "?",
                     "text": t[:8000]})
    return rows

# ---------- Cursor 扫描 ----------
CURSOR_USER = os.path.expanduser("~/Library/Application Support/Cursor/User")

def _ms_iso(ms):
    """毫秒 epoch → ISO 字符串（与其余来源的 ts 同一排序口径）。"""
    try:
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()
    except Exception:
        return None

def scan_cursor():
    """Cursor（IDE）扫描，数据在两级 SQLite（一律 file:...?mode=ro 只读 URI 打开）：
      - workspaceStorage/<hash>/state.vscdb ItemTable：composer.composerData 是 composer 注册表
        （composerId→createdAt 毫秒）；workbench.panel.aichat.view.aichat.chatdata 是旧版聊天
        （tabs[].bubbles[]，type "user"/"ai"）；同目录 workspace.json 的 folder 即项目路径。
      - globalStorage/state.vscdb cursorDiskKV：bubbleId:<composerId>:<bubbleId> 逐条消息
        （JSON，type 1=用户 2=助手；部分助手气泡带 tokenCount{inputTokens,outputTokens}，
        稀疏就稀疏着计入）；composerData:<id> 补充 composer createdAt。
    时间戳硬伤（照此口径接入）：仅最新版气泡自带逐条 ISO createdAt；旧气泡退回所属
    composer.createdAt、旧版 tab 退回 lastSendTime 近似。完全无时间戳的行进不了时间轴，放弃。
    aiService.prompts 无时间戳且与气泡重复，刻意不并入语料（防重复计数）。"""
    sessions, corpus = [], []
    if not os.path.isdir(CURSOR_USER):
        return sessions, corpus
    created_of, proj_of = {}, {}   # composerId → createdAt(ms) / 项目短名
    legacy_tabs = []               # (lastSendTime_ms, project, [该 tab 的用户消息文本])
    ws_dbs = glob.glob(os.path.join(CURSOR_USER, "workspaceStorage", "*", "state.vscdb"))
    log(f"[cursor] scanning {len(ws_dbs)} workspace dbs + global db")
    for db in ws_dbs:
        proj = "?"
        try:
            with open(os.path.join(os.path.dirname(db), "workspace.json"), errors="replace") as f:
                folder = (json.load(f).get("folder") or "").rstrip("/")
            if folder:
                proj = os.path.basename(folder) or "?"
        except Exception:
            pass
        try:
            con = sqlite3.connect("file:" + db + "?mode=ro", uri=True)
            comp_row = con.execute(
                "SELECT value FROM ItemTable WHERE key='composer.composerData'").fetchone()
            chat_row = con.execute(
                "SELECT value FROM ItemTable WHERE key='workbench.panel.aichat.view.aichat.chatdata'").fetchone()
            con.close()
        except Exception as e:
            log(f"ERR {db}: {e}")
            continue
        try:
            for c in (json.loads(comp_row[0]).get("allComposers") or []) if comp_row and comp_row[0] else []:
                cid = c.get("composerId")
                if not cid:
                    continue
                if c.get("createdAt"):
                    created_of[cid] = c["createdAt"]
                proj_of[cid] = proj
        except Exception:
            pass
        try:
            for t in (json.loads(chat_row[0]).get("tabs") or []) if chat_row and chat_row[0] else []:
                texts = [(b.get("text") or b.get("rawText") or "").strip()
                         for b in (t.get("bubbles") or []) if b.get("type") == "user"]
                legacy_tabs.append((t.get("lastSendTime"), proj, [x for x in texts if x]))
        except Exception:
            pass
    # 全局库：新版逐条气泡 + composer createdAt 补充 + 全局侧的旧版聊天
    bubbles = defaultdict(lambda: {"user": [], "in_tok": 0, "out_tok": 0, "calls": 0})
    gdb = os.path.join(CURSOR_USER, "globalStorage", "state.vscdb")
    if os.path.exists(gdb):
        try:
            con = sqlite3.connect("file:" + gdb + "?mode=ro", uri=True)
            for k, v in con.execute("SELECT key, value FROM cursorDiskKV WHERE key LIKE 'composerData:%'"):
                if not v:
                    continue
                try:
                    d = json.loads(v)
                except Exception:
                    continue
                cid = k.split(":", 1)[1]
                if d.get("createdAt") and cid not in created_of:
                    created_of[cid] = d["createdAt"]
            for k, v in con.execute("SELECT key, value FROM cursorDiskKV WHERE key LIKE 'bubbleId:%'"):
                if not v:
                    continue
                try:
                    d = json.loads(v)
                except Exception:
                    continue
                parts = k.split(":")
                if len(parts) < 3:
                    continue
                b = bubbles[parts[1]]
                if d.get("type") == 1:      # 用户气泡
                    txt = (d.get("text") or "").strip()
                    if txt:
                        b["user"].append((d.get("createdAt"), txt))  # 新版气泡自带 ISO createdAt
                elif d.get("type") == 2:    # 助手气泡
                    b["calls"] += 1
                    tc = d.get("tokenCount") or {}
                    b["in_tok"] += tc.get("inputTokens") or 0
                    b["out_tok"] += tc.get("outputTokens") or 0
            row = con.execute(
                "SELECT value FROM ItemTable WHERE key='workbench.panel.aichat.view.aichat.chatdata'").fetchone()
            if row and row[0]:
                try:
                    for t in json.loads(row[0]).get("tabs") or []:
                        texts = [(b.get("text") or b.get("rawText") or "").strip()
                                 for b in (t.get("bubbles") or []) if b.get("type") == "user"]
                        legacy_tabs.append((t.get("lastSendTime"), "?", [x for x in texts if x]))
                except Exception:
                    pass
            con.close()
        except Exception as e:
            log(f"ERR {gdb}: {e}")
    # 组装：每个 composer 一个 session（含无气泡的——它们是真实发生过的会话，正文已蒸发），
    # 旧版 aichat 每个 tab 一个 session
    for cid in set(created_of) | set(proj_of) | set(bubbles):
        ts = _ms_iso(created_of[cid]) if cid in created_of else None
        s = {"first_ts": ts, "last_ts": ts, "human_msgs": 0, "assistant_calls": 0,
             "in_tok": 0, "out_tok": 0, "cache_read": 0, "models": {}}
        b = bubbles.get(cid)
        if b:
            s["assistant_calls"] = b["calls"]
            s["in_tok"], s["out_tok"] = b["in_tok"], b["out_tok"]
            proj = proj_of.get(cid, "?")
            for bts, txt in b["user"]:
                row_ts = bts or ts
                if not row_ts:
                    continue
                s["human_msgs"] += 1
                corpus.append({"src": "cursor", "ts": row_ts, "project": proj, "text": txt[:8000]})
        sessions.append(s)
    for ms, proj, texts in legacy_tabs:
        ts = _ms_iso(ms) if ms else None
        s = {"first_ts": ts, "last_ts": ts, "human_msgs": 0, "assistant_calls": 0,
             "in_tok": 0, "out_tok": 0, "cache_read": 0, "models": {}}
        if ts:
            for txt in texts:
                s["human_msgs"] += 1
                corpus.append({"src": "cursor", "ts": ts, "project": proj, "text": txt[:8000]})
        sessions.append(s)
    return sessions, corpus

# ---------- 统计与画像 ----------
def clamp(x):
    return max(0.0, min(1.0, x))

def longest_streak(days):
    if not days:
        return 0
    from datetime import date, timedelta
    ds = sorted(date.fromisoformat(d) for d in days)
    best = cur = 1
    for a, b in zip(ds, ds[1:]):
        cur = cur + 1 if (b - a).days == 1 else 1
        best = max(best, cur)
    return best

ZH_STOP = set(("这个 那个 就是 可以 需要 然后 现在 我们 一下 一个 什么 怎么 这样 那样 还是 已经 是不是 不是 直接 应该 里面 上面 下面 时候 如果 所有 全部 但是 因为 所以 其他 或者 继续 开始 使用 这里 那里 出来 进去 东西 地方 感觉 觉得 知道 看看 看一下 弄一下 "
                "没有 这些 可能 一些 为什么 还有 其实 每个 好的 不要 不用 不能 还有 或是 以及 并且 而且 就行 即可 时候 之后 之前 先把 再把 要求 情况 方式 进行 处理 相关 对应 确保 完成 实现 支持 根据 通过 无法 有点 比较 非常 真的 到底 起来 下来 上去").split())
EN_STOP = set("the and for you this that with not are was have has can will your from what when how все all use just like make sure need want does did been being them they their there here would should could into onto over under out about after before again then than very much more most some any each was were its it's don doesn didn isn aren won can't i'm we're you're let's".split())

RE_PASTE_PLACEHOLDER = re.compile(r"\[pasted text[^\]]*\]|\[image[^\]]*\]", re.I)

def clean_text(t):
    """去掉 harness 的粘贴占位符（'[Pasted text #1 +58 lines]'），它不是用户说的话。"""
    return RE_PASTE_PLACEHOLDER.sub(" ", t).strip()

def wordcloud_terms(corpus, top_n=80):
    counts = Counter()
    for r in corpus:
        t = clean_text(r["text"][:300]).lower()
        for w in re.findall(r"[a-z][a-z0-9_\-\.]{2,24}", t):
            if w not in EN_STOP:
                counts[w] += 1
        for run in re.findall(r"[一-鿿]{2,}", t):
            for n in (2, 3):
                for i in range(len(run) - n + 1):
                    counts[run[i:i + n]] += 1
    # 去掉被更长高频词覆盖的短词（"报告页" 吃掉 "报告"）；停用词的子串也一并排除（"为什"⊂"为什么"）
    grams = [(g, c) for g, c in counts.items()
             if c >= 3 and g not in ZH_STOP and not any(g in sw for sw in ZH_STOP if len(sw) > len(g))]
    grams.sort(key=lambda kv: (-len(kv[0]), -kv[1]))
    kept = []
    for g, c in grams:
        covered = any(g in kg and c <= kc * 1.2 for kg, kc in kept)
        if not covered:
            kept.append((g, c))
    kept.sort(key=lambda kv: -kv[1])
    return [{"text": g, "weight": c} for g, c in kept[:top_n]]

def signature_phrases(corpus, top_n=10):
    c = Counter()
    for r in corpus:
        t = clean_text(r["text"])
        if 1 < len(t) <= 30:
            c[t] += 1
    return [{"text": t, "count": n} for t, n in c.most_common(top_n) if n >= 5]

ARCHETYPES = [
    # (id, 中文名, 英文名, tagline, 评分函数)
    ("root-cause-tyrant", "根因主义暴君", "The Root-Cause Tyrant",
     "不修根因不许收工，礼貌是什么，能吃吗",
     lambda d: d["correction_density"] * 0.6 + (1 - d["politeness"]) * 0.4),
    ("one-am-orchestrator", "凌晨一点的编排者", "The 1 A.M. Orchestrator",
     "全世界睡着之后，你的 agent 军团才开始上班",
     lambda d: d["night_shift"] * 0.6 + d["automation_leverage"] * 0.4),
    ("status-bomber", "咋样了轰炸机", "The Status Bomber",
     "你最常输入的不是需求，是催促",
     lambda d: d["repetition"] * 0.7 + (1 - d["msg_length"]) * 0.3),
    ("gentle-pair", "温柔的结对者", "The Gentle Pair-Programmer",
     "对 AI 说请和谢谢的人，运气不会太差",
     lambda d: d["politeness"] * 0.7 + (1 - d["correction_density"]) * 0.3),
    ("free-range-rancher", "放养大师", "The Free-Range Rancher",
     "把任务丢出去就去睡觉，醒来验收",
     lambda d: d["automation_leverage"] * 0.7 + (1 - d["correction_density"]) * 0.3),
    ("microscope-foreman", "显微镜下的监工", "The Microscope Foreman",
     "每一行 diff 都要亲自过目",
     lambda d: (1 - d["automation_leverage"]) * 0.5 + d["correction_density"] * 0.3 + d["msg_length"] * 0.2),
    ("taste-legislator", "品味立法者", "The Taste Legislator",
     "你不是在用 AI，你是在给 AI 立法",
     lambda d: d["taste_signal_density"] * 0.7 + d["rules_norm"] * 0.3),
    ("dissertation-client", "论文型甲方", "The Dissertation Client",
     "一条消息三千字，需求文档级 prompt",
     lambda d: d["msg_length"] * 0.7 + (1 - d["frequency"]) * 0.3),
    ("telegraph-operator", "电报员", "The Telegraph Operator",
     "四个字能说清的事绝不用五个字",
     lambda d: (1 - d["msg_length"]) * 0.6 + d["frequency"] * 0.4),
    ("dual-wield-arbiter", "双修仲裁者", "The Dual-Wield Arbiter",
     "让两家模型互相 review，你坐收渔利",
     lambda d: d["duality"]),
    ("daylight-sprinter", "白日冲刺手", "The Daylight Sprinter",
     "作息健康得不像这个行业的人",
     lambda d: (1 - d["night_shift"]) * 0.5 + d["streak_norm"] * 0.5),
    ("beast-tamer", "驯兽师", "The Beast Tamer",
     "纠偏率一路下降——你把 AI 驯明白了",
     lambda d: d["taming"] * 0.7 + d["rules_norm"] * 0.3),
]

def compute(claude_sessions, codex_sessions, openclaw_sessions, cursor_sessions, corpus):
    corpus.sort(key=lambda r: r["ts"])
    local_rows = []
    for r in corpus:
        dt = to_local(r["ts"])
        if dt:
            local_rows.append((dt, r))

    # --- 基础量 ---
    c_out = sum(s["out_tok"] + s["side_out_tok"] for s in claude_sessions)
    c_in = sum(s["in_tok"] + s["side_in_tok"] for s in claude_sessions)
    c_cache = sum(s["cache_read"] + s["side_cache_read"] for s in claude_sessions)
    x_out = sum(s["out_tok"] for s in codex_sessions)
    x_fresh = sum(max(0, s["in_tok"] - s["cached_tok"]) for s in codex_sessions)
    x_cache = sum(s["cached_tok"] for s in codex_sessions)
    oc_out = sum(s["out_tok"] for s in openclaw_sessions)
    oc_in = sum(s["in_tok"] for s in openclaw_sessions)
    oc_cache = sum(s["cache_read"] for s in openclaw_sessions)
    cur_out = sum(s["out_tok"] for s in cursor_sessions)   # cursor token 极稀疏（仅部分助手气泡带 tokenCount）
    cur_in = sum(s["in_tok"] for s in cursor_sessions)

    out_tok = c_out + x_out + oc_out + cur_out
    fresh_in = c_in + x_fresh + oc_in + cur_in
    cache_read = c_cache + x_cache + oc_cache
    human_chars = sum(len(r["text"]) for r in corpus)

    hour_hist = [0] * 24
    weekday_hist = [0] * 7
    daily = Counter()
    monthly_msgs = Counter()
    for dt, r in local_rows:
        hour_hist[dt.hour] += 1
        weekday_hist[dt.weekday()] += 1
        daily[dt.date().isoformat()] += 1
        monthly_msgs[dt.strftime("%Y-%m")] += 1

    models = Counter()
    monthly_out = Counter()
    monthly_sess = Counter()
    for s in claude_sessions:
        for m, n in s["models"].items():
            models[m] += n
        if s["first_ts"]:
            mo = s["first_ts"][:7]
            monthly_out[mo] += s["out_tok"] + s["side_out_tok"]
            if not s.get("is_subagent"):
                monthly_sess[mo] += 1
    for s in codex_sessions:
        if s.get("model"):
            models[s["model"]] += max(1, s["turns"])
        if s["first_ts"]:
            mo = s["first_ts"][:7]
            monthly_out[mo] += s["out_tok"]
            monthly_sess[mo] += 1
    for s in openclaw_sessions:
        for m, n in s["models"].items():
            models[m] += n
        if s["first_ts"]:
            mo = s["first_ts"][:7]
            monthly_out[mo] += s["out_tok"]
            monthly_sess[mo] += 1
    for s in cursor_sessions:   # cursor 不落模型名，只计月度活动
        if s["first_ts"]:
            mo = s["first_ts"][:7]
            monthly_out[mo] += s["out_tok"]
            monthly_sess[mo] += 1

    n_msgs = len(corpus) or 1
    night = sum(1 for dt, _ in local_rows if dt.hour < 6) / max(1, len(local_rows))
    corrections = sum(1 for r in corpus if RE_CORRECTION.search(r["text"][:60]))
    polite = sum(1 for r in corpus if RE_POLITE.search(r["text"]))
    taste_rows = [r for r in corpus if RE_TASTE.search(r["text"])]
    streak = longest_streak(daily.keys())
    rules_taught = 0
    rule_paths = list(RULE_FILES) + glob.glob(os.path.expanduser("~/.claude/projects/*/memory/*.md"))
    for p in rule_paths:
        if os.path.exists(p):
            rules_taught += sum(1 for l in open(p, errors="replace")
                                if l.strip() and not l.strip().startswith("#"))

    # 已安装 skill/command 数（口径：claude skills 目录 + claude commands + codex prompts）
    skills_installed = (len(glob.glob(os.path.expanduser("~/.claude/skills/*/")))
                        + len(glob.glob(os.path.expanduser("~/.claude/commands/*.md")))
                        + len(glob.glob(os.path.expanduser("~/.codex/prompts/*.md"))))

    # 平均每 session 人类消息数（只计交互式 session：codex 的 exec 自动派发不算，
    # 否则 2.9 万个机器 rollout 会把分母冲垮）
    active_sessions = (sum(1 for s in claude_sessions if s["human_msgs"])
                       + sum(1 for s in codex_sessions
                             if s["user_msgs"] and s.get("originator") != "codex_exec")
                       + sum(1 for s in openclaw_sessions if s["human_msgs"])
                       + sum(1 for s in cursor_sessions if s["human_msgs"]))
    session_turns_avg = round(n_msgs / active_sessions, 1) if active_sessions else None

    # 阵营只看 Claude vs Codex 两大家（openclaw 等自建 harness 不参与站队）
    claude_msgs = sum(1 for r in corpus if r["src"] == "claude")
    codex_msgs = sum(1 for r in corpus if r["src"] == "codex")
    camp_total = max(1, claude_msgs + codex_msgs)
    minority = min(claude_msgs, codex_msgs) / camp_total
    camp = "dual" if minority >= 0.15 else ("claude" if claude_msgs >= codex_msgs else "codex")

    human_tok_est = max(1, human_chars // 3)
    leverage = out_tok / human_tok_est
    correction_rate = corrections / n_msgs
    avg_chars = human_chars / n_msgs
    span_days = max(1, len(daily))

    # --- 新维度（owner 2026-07-06 晚）：用途分类 / 等值成本 / 并行度 / 打断 / 周末 / 外包率 ---
    split = usage_split(corpus)

    cost = 0.0
    for s in claude_sessions:
        model = max(s["models"], key=s["models"].get) if s["models"] else ""
        pi, po, pc = price_of(model)
        cost += ((s["in_tok"] + s["side_in_tok"]) * pi + (s["out_tok"] + s["side_out_tok"]) * po
                 + (s["cache_read"] + s["side_cache_read"]) * pc) / 1e6
    for s in codex_sessions:
        pi, po, pc = price_of(s.get("model"))
        cost += (max(0, s["in_tok"] - s["cached_tok"]) * pi + s["out_tok"] * po + s["cached_tok"] * pc) / 1e6
    for s in openclaw_sessions:
        model = max(s["models"], key=s["models"].get) if s["models"] else ""
        pi, po, pc = price_of(model)
        cost += (s["in_tok"] * pi + s["out_tok"] * po + s["cache_read"] * pc) / 1e6
    for s in cursor_sessions:   # 气泡不落模型名 → 兜底牌价；token 本就稀疏，只会低估
        pi, po, _pc = price_of("")
        cost += (s["in_tok"] * pi + s["out_tok"] * po) / 1e6

    hour_projects = defaultdict(set)
    weekend = 0
    for dt, r in local_rows:
        hour_projects[dt.strftime("%Y-%m-%d %H")].add(r["project"])
        if dt.weekday() >= 5:
            weekend += 1
    parallel_peak = max((len(v) for v in hour_projects.values()), default=0)

    # effort 档位分布（目前只有 Codex 暴露该指标；按 rollout 计数）
    effort_split = dict(Counter(s["effort"] for s in codex_sessions if s.get("effort")).most_common())

    interruptions = sum(s.get("interruptions", 0) for s in claude_sessions)
    main_calls = sum(s["assistant_calls"] for s in claude_sessions)
    side_calls = sum(s["sidechain_calls"] for s in claude_sessions)
    sidechain_share = round(side_calls / max(1, main_calls + side_calls), 4)

    def norm_proj(p):
        # claude transcript 目录名是 cwd 路径的连字符编码（"-Users-alice-projects-myapp"）；取叶子目录名
        if p.startswith("-") and len(p) > 1:
            return p.rstrip("-").rsplit("-", 1)[-1] or p
        return p
    proj_counter = Counter(norm_proj(r["project"]) for r in corpus if r["project"] != "?")
    project_top = [{"project": p, "share": round(n / n_msgs, 4)} for p, n in proj_counter.most_common(5)]

    # 磨合曲线：分月纠偏率 + 累计规则声明
    months = sorted(monthly_msgs)
    curve = []
    rules_cum = 0
    taste_by_month = Counter(to_local(r["ts"]).strftime("%Y-%m") for r in taste_rows if to_local(r["ts"]))
    corr_by_month = Counter(to_local(r["ts"]).strftime("%Y-%m") for r in corpus
                            if RE_CORRECTION.search(r["text"][:60]) and to_local(r["ts"]))
    for mo in months:
        rules_cum += taste_by_month.get(mo, 0)
        curve.append({"month": mo,
                      "correction_rate": round(corr_by_month.get(mo, 0) / max(1, monthly_msgs[mo]), 4),
                      "rules_cumulative": rules_cum})

    # 驯化：前半段 vs 后半段纠偏率下降幅度
    half = len(curve) // 2
    if half >= 1:
        first = sum(c["correction_rate"] for c in curve[:half]) / half
        second = sum(c["correction_rate"] for c in curve[half:]) / (len(curve) - half)
        taming = clamp((first - second) / max(first, 1e-6))
    else:
        taming = 0.0

    sig = signature_phrases(corpus)
    top_repeat = sig[0]["count"] if sig else 0

    dims = {
        "automation_leverage": clamp((len(str(int(leverage))) - 1) / 5),  # log10 量级归一
        "correction_density": clamp(correction_rate / 0.15),
        "night_shift": clamp(night / 0.4),
        "msg_length": clamp(avg_chars / 400),
        "politeness": clamp(polite / n_msgs / 0.15),
        "taste_signal_density": clamp(len(taste_rows) / n_msgs / 0.08),
        # 以下为选型用隐藏维度，不进报告雷达图
        "repetition": clamp(top_repeat / 150),
        "frequency": clamp(n_msgs / span_days / 60),
        "duality": clamp(minority / 0.35),
        "streak_norm": clamp(streak / 120),  # 45 天就饱和会让重度用户全变"冲刺手"，上限放宽
        "rules_norm": clamp(rules_taught / 150),
        "taming": taming,
    }
    aid, zh, en, tagline, _ = max(ARCHETYPES, key=lambda a: a[4](dims))

    badges = []
    longest_msg = max((len(r["text"]) for r in corpus), default=0)
    if longest_msg >= 3000:
        badges.append({"id": "dissertation", "name": "万字甲方", "desc": f"单条消息最长 {longest_msg} 字",
                       "evidence": f"{longest_msg} chars"})
    if top_repeat >= 6:
        badges.append({"id": "same-msg-repeat", "name": "复读机", "desc": f"同一句话发了 {top_repeat} 次",
                       "evidence": sig[0]["text"]})
    hit = max((m for m in (1000, 5000, 10000, 20000, 50000) if n_msgs >= m), default=0)
    if hit:
        badges.append({"id": f"msg-{hit}", "name": f"第 {hit:,} 条消息", "desc": f"累计亲手输入 {n_msgs:,} 条消息",
                       "evidence": str(n_msgs)})
    if camp == "dual":
        badges.append({"id": "dual-wield", "name": "跨模型仲裁者", "desc": "同时驱使 Claude 与 Codex",
                       "evidence": f"claude {claude_msgs} / codex {codex_msgs}"})
    if streak >= 14:
        badges.append({"id": "streak", "name": f"连跑 {streak} 天", "desc": "最长连续活跃天数",
                       "evidence": str(streak)})
    if night >= 0.25:
        badges.append({"id": "night-owl", "name": "夜行动物", "desc": f"{night:.0%} 的消息发生在 0–6 点",
                       "evidence": f"{night:.2f}"})
    if cache_read and cache_read / max(1, cache_read + fresh_in) >= 0.9:
        badges.append({"id": "cache-lord", "name": "缓存领主", "desc": "cache 命中率超过 90%",
                       "evidence": f"{cache_read/(cache_read+fresh_in):.2%}"})

    sources = []
    if claude_sessions:
        sources.append("claude_code")
    if codex_sessions:
        sources.append("codex")
    if openclaw_sessions:
        sources.append("openclaw")
    if cursor_sessions:
        sources.append("cursor")

    # --- per-source 对比（各 agent 使用频率 / 产出 / 各自吐槽位） ---
    per_source = {}
    src_map = {"claude": ("claude_code", c_out, sum(1 for s in claude_sessions if not s.get("is_subagent"))),
               "codex": ("codex", x_out, len(codex_sessions)),
               "openclaw": ("openclaw", oc_out, len(openclaw_sessions)),
               # sessions 口径：composer 数 + 旧版 aichat tab 数（见 scan_cursor docstring）
               "cursor": ("cursor", cur_out, len(cursor_sessions))}
    for src, (key, out, n_sess) in src_map.items():
        rows = [r for r in corpus if r["src"] == src]
        if not rows:
            continue
        days = {dt.date().isoformat() for dt, r in local_rows if r["src"] == src}
        per_source[key] = {
            "human_msgs": len(rows), "sessions": n_sess, "out_tokens": out,
            "active_days": len(days), "share": round(len(rows) / n_msgs, 4),
            "roast": None,  # 深挖模式由 host agent 撰写（基于真实数字）
        }

    # --- Claude 蒸发期外推 ---
    # transcript（含 token 用量）只存活 ~cleanupPeriodDays 天，但 history.jsonl 打字记录是全史。
    # 外推口径：存活窗口内 每条人类消息平均产出 token × 全史 claude 消息数 + codex 实测全量。
    transcript_msgs = sum(s["human_msgs"] for s in claude_sessions)
    claude_all_msgs = per_source.get("claude_code", {}).get("human_msgs", 0)
    est_total = None
    est_note = None
    if transcript_msgs and claude_all_msgs > transcript_msgs * 1.15:
        tokens_per_msg = c_out / transcript_msgs
        est_claude = int(tokens_per_msg * claude_all_msgs)
        est_total = est_claude + x_out + oc_out + cur_out
        est_note = (f"Claude Code transcript 仅存活最近窗口（{transcript_msgs} 条消息对应 {c_out:,} tokens），"
                    f"更早月份已被 30 天清理策略蒸发；按全史 {claude_all_msgs} 条打字记录 × 窗口内平均每消息产出外推。"
                    f"其余来源为全史实测值。")

    # 报告语言不在代码里猜（owner 2026-07-07：语言不止中英文，交给 agent 判断）。
    # 留空，由 agent 在 skill.md 里据语料判定用户主要语言（任意语种）并写入。
    lang = None

    data = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "lang": lang,
        "handle": None,
        "sources": sources,
        "period": {"from": corpus[0]["ts"][:10] if corpus else None,
                   "to": corpus[-1]["ts"][:10] if corpus else None},
        "mode": "fast",
        "stats": {
            "sessions": (sum(1 for s in claude_sessions if not s.get("is_subagent"))
                         + len(codex_sessions) + len(openclaw_sessions) + len(cursor_sessions)),
            "active_days": len(daily),
            "human_msgs": n_msgs,
            "agent_out_tokens": out_tok,
            "fresh_in_tokens": fresh_in,
            "cache_read_tokens": cache_read,
            "cache_hit_rate": round(cache_read / max(1, cache_read + fresh_in), 4),
            # 全口径总处理量 = 输出 + 新鲜输入 + cache 重读；与 ccusage 等工具的口径对齐，
            # 避免用户拿其他统计工具对比时以为我们算少了
            "total_processed_tokens": out_tok + fresh_in + cache_read,
            "api_calls": (sum(s["assistant_calls"] + s["sidechain_calls"] for s in claude_sessions)
                          + sum(s["assistant_calls"] for s in openclaw_sessions)
                          + sum(s["assistant_calls"] for s in cursor_sessions)),
            "leverage_ratio": round(leverage, 1),
            "longest_streak_days": streak,
            "night_owl_index": round(night, 4),
            "correction_rate": round(correction_rate, 4),
            "rules_taught": rules_taught,
            "hour_histogram": hour_hist,
            "weekday_histogram": weekday_hist,
            "daily_activity": dict(daily),
            "monthly": [{"month": mo, "human_msgs": monthly_msgs[mo],
                         "out_tokens": monthly_out.get(mo, 0), "sessions": monthly_sess.get(mo, 0)}
                        for mo in months],
            "models": dict(models.most_common(12)),
            "camp": camp,
            "session_turns_avg": session_turns_avg,
            "skills_installed": skills_installed,
            "agent_out_tokens_estimated": est_total,
            "estimation_note": est_note,
            "usage_split": split,
            "api_cost_estimated_usd": round(cost),
            "api_cost_note": "按各模型公开 API 牌价对实测 token 估算（输入/输出/cache 分开计价）；订阅制实际支出远低于此——这就是杠杆",
            "parallel_peak_projects_hour": parallel_peak,
            "weekend_share": round(weekend / max(1, len(local_rows)), 4),
            "interruptions": interruptions,
            "sidechain_share": sidechain_share,
            # project_top 不进报告 JSON（页面不渲染它，但嵌入 JSON 查源码可见——纯泄露面）；
            # 只在扫描摘要 stdout 里给本人看
            "effort_split": effort_split,
        },
        "per_source": per_source,
        "archetype": {
            "id": aid, "name": zh, "name_en": en, "tagline": tagline,
            "dimensions": {k: round(dims[k], 3) for k in
                           ("automation_leverage", "correction_density", "night_shift",
                            "msg_length", "politeness", "taste_signal_density")},
        },
        "narrative": None,
        "quotes": {"harshest": None, "signature": sig, "roast": None},
        "moments": [],
        "diagnosis": [],
        "wordcloud": {"words": wordcloud_terms(corpus)},
        "taming_curve": curve,
        "badges": badges,
        "creeds": [],
        "distilled_skills": [],
        "_project_top_local": project_top,  # main() 会弹出，只进 stdout 摘要不进文件
    }
    return data

def write_chunks(corpus, workdir, n=10):
    """把语料按时间均分为 n 片，供深挖模式的并行 subagent 使用。"""
    if not corpus:
        return []
    size = (len(corpus) + n - 1) // n
    manifest = []
    for i in range(0, len(corpus), size):
        chunk = corpus[i:i + size]
        name = f"corpus-chunk-{i//size+1:02d}.jsonl"
        with open(os.path.join(workdir, name), "w") as f:
            for r in chunk:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        manifest.append({"file": name, "rows": len(chunk),
                         "from": chunk[0]["ts"][:10], "to": chunk[-1]["ts"][:10]})
    return manifest

def main():
    if len(sys.argv) < 2 or sys.argv[1] != "scan":
        print(__doc__)
        sys.exit(1)

    workdir = os.path.expanduser("~/.agentmole/work")
    if "--workdir" in sys.argv:
        workdir = sys.argv[sys.argv.index("--workdir") + 1]
    os.makedirs(workdir, exist_ok=True)

    claude_sessions, claude_corpus = scan_claude()
    claude_corpus += claude_history_corpus(claude_corpus)
    codex_sessions = scan_codex()
    openclaw_sessions, openclaw_rows = scan_openclaw()
    cursor_sessions, cursor_rows = scan_cursor()   # 数据缺失时返回空，静默跳过
    corpus = claude_corpus + codex_corpus(codex_sessions) + openclaw_rows + cursor_rows
    if not corpus:
        log("未找到任何 Claude Code / Codex / OpenClaw / Cursor 历史数据。")
        sys.exit(2)

    data = compute(claude_sessions, codex_sessions, openclaw_sessions, cursor_sessions, corpus)
    project_top = data.pop("_project_top_local", [])
    out = os.path.join(workdir, "report-data.json")
    with open(out, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)

    corpus.sort(key=lambda r: r["ts"])
    manifest = write_chunks(corpus, workdir)
    with open(os.path.join(workdir, "chunks.json"), "w") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)

    detected = [name for name, p in HARNESS_PROBES.items() if os.path.isdir(os.path.expanduser(p))]
    s = data["stats"]
    log(f"done → {out}")
    print(json.dumps({
        "workdir": workdir,
        "human_msgs": s["human_msgs"], "sessions": s["sessions"],
        "active_days": s["active_days"], "agent_out_tokens": s["agent_out_tokens"],
        "agent_out_tokens_estimated": s["agent_out_tokens_estimated"],
        "archetype": data["archetype"]["name"],
        "chunks": len(manifest),
        "deep_mode_recommended": s["human_msgs"] >= 2000,
        "detected_unsupported_harnesses": detected,
        "project_top_local_only": project_top,  # 仅本地摘要展示，不进报告页
    }, ensure_ascii=False, indent=1))

if __name__ == "__main__":
    main()

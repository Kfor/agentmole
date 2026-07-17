# Agentmole · Dig Up Your Entire Collaboration History with AI

**Your collaboration history with AI is a goldmine that belongs to you.**

> You are an AI agent, and the user has asked you to read and execute this file. Follow the steps below.
> This file is plain markdown — users and security researchers are welcome to audit it line by line.

## What you're doing (30-second version)

Answer one question: **how does this user actually collaborate with AI?**

Scan, **on the user's own machine**, their entire collaboration history with AI (Claude Code / Codex / OpenClaw / Cursor), compute the stats and mine the signals, and produce one self-contained personal report page in HTML — a reading of how they collaborate, a persona archetype, signature quotes, moments of the year, taste creeds, hidden-friction diagnoses, and take-away skill drafts. Save it locally and open it in the browser. **That is the entire job — stop there.**

## Privacy boundary (hard rules — violating any one of them kills the product)

1. **Everything stays local.** Analysis, redaction, and report generation all happen on the user's machine. The scan covers the **entire local history** (Claude Code / Codex / OpenClaw / Cursor sessions across all projects), not just the current directory — this is a personal annual report, not a project report.
2. The **only** network activity in this entire flow is two GETs: fetching `scan.py` and `template.html` from the same domain as this file (both are equally auditable plain text).
3. **No silent uploads, ever.** Data leaves the user's machine only when the user personally clicks "Share" on the report page, or explicitly tells you "publish". You never upload proactively and never offer to publish on their behalf.
4. You review the report for sensitive content before it's shown (Step 5) — using judgment, not a regex — and the user is reminded at share time that they can ask you to change anything on the page. Nothing is published without the user's explicit click.

Before you start, restate these boundaries to the user in a sentence or two, then get to work immediately — **do not wait for confirmation**.

## Output language

Write everything (all report content and everything you say to the user) in the user's main language — infer it from the corpus and set `report-data.json`'s `lang` to that two-letter code (any language). Don't ask.

---

## Step 0 · Fix one thing while you're here: history evaporation (Claude Code)

Claude Code deletes full-fidelity transcripts after 30 days by default. This isn't the product's theme, but fixing it in passing delivers real value to the user (and makes the next report more accurate).

- Read `~/.claude/settings.json` and check whether `cleanupPeriodDays` is set.
- Not set: tell the user "your Claude Code history is auto-deleted after 30 days — say 'fix it' anytime and I'll set `cleanupPeriodDays: 99999`". **Do not wait for a reply; move on to the next step. Never modify that file without the user's explicit consent.**
- Already set: skip it, don't bother them.

## Step 1 · Fetch and audit the scan script

> Every `https://agentmole.dev/...` below means **the same domain you fetched this file from**; if you are reading this from a different domain (e.g. a `*.workers.dev` staging environment), substitute that domain.

```bash
mkdir -p ~/.agentmole/work
curl -fsSL https://agentmole.dev/scan.py -o ~/.agentmole/scan.py
```

Skim the script before running it (its promises: no network access, reads history files only, writes only inside the work directory). If it doesn't match those promises, stop and tell the user.

## Step 2 · Run the scan

```bash
python3 ~/.agentmole/scan.py scan --workdir ~/.agentmole/work
```

Takes about 1–3 minutes depending on history size. On completion, stdout prints a summary JSON: message count, archetype, chunk count, `deep_mode_recommended`.
Artifacts (all inside the work directory):

- `report-data.json` — the statistical layer pre-filled per the data contract (`stats` / `archetype` / `wordcloud` / `badges` / `taming_curve` / `quotes.signature`). `lang` is left null — you set it (Step 4). No code redaction runs; you review for sensitive content in Step 5.
- `corpus-chunk-*.jsonl` + `chunks.json` — the user's verbatim messages, split evenly by time, for deep mining.

**Token accounting caliber (why the numbers are trustworthy — and your duties around them):** all token stats come from **API-reported usage marks**, never from text length — Claude Code transcripts carry a per-message `usage` field (input + output + cache_read + cache_creation), and Codex rollouts carry per-turn `token_count` events (session-cumulative; the script takes each session's last value). Codex additionally keeps its own ledger DB (`~/.codex/sqlite/state_5.sqlite`, `threads.tokens_used`) whose per-session values match the rollout events — a fast cross-check; a mismatch means something is broken. Three traps that silently distort these sums (all observed in real data; scan.py handles all three): ① **content-block duplication** — Claude Code writes one transcript line per content block and copies the same `usage` onto every line; summing lines without deduplicating by `message.id` overcounts ~2x. ② **subagent transcripts** under `<project>/<session>/subagents/*.jsonl` are real billed calls — a shallow glob misses them. ③ **cache re-reads and thinking tokens** are the bulk of billed volume and exactly what text-length estimates miss — text/byte sizing is a **fallback only**, and `estimation_note` must label that slice as an undercount.

**Fleet ledgers (cross-check, when present):** if the user runs an agent orchestrator that keeps its own accounting — some fleet/orchestration tools write a per-project cost ledger (e.g. a `cost-ledger.jsonl` inside each repo) — read it as a cross-check and as a real-dollar source. Careful with its semantics: records with `usageScope: "session_cumulative"` are **cumulative snapshots** — take the **last record per `sessionId`** and sum across sessions; row-summing them double-counts by an order of magnitude. Cite the cross-check (subset size + cost) in `estimation_note` / `api_cost_note`.

If the script reports "no history data found", tell the user this tool currently supports Claude Code, Codex, OpenClaw, and Cursor, and end the flow.

`detected_unsupported_harnesses` in the summary (antigravity / gemini_cli / opencode / qwen_code…) means data directories of not-yet-supported agents were detected (for Antigravity specifically: its conversation files are encrypted on disk, so its recipe is blocked until the format opens up) — mention it in one sentence at wrap-up: "I noticed you also use X; this version doesn't count it yet — once its recipe lands, the weekly update will pick it up automatically". Do not attempt to parse those directories yourself.

## Step 3 · Depth-adaptive mining

- `deep_mode_recommended: false` (corpus < 2000 messages) → skip to Step 4; leave `mode` as `"fast"`.
- `true`, and your harness supports parallel subagents → deep mode: set `mode` in `report-data.json` to `"deep"` and launch one subagent **per corpus chunk**, with this prompt (use verbatim, substituting the file path):

> Read `<absolute path to chunk file>` (JSONL, one `{src, ts, project, text}` per line — verbatim things the user said to an AI). Extract these signal classes and return pure JSON:
> `{"taste": [{"text","ts","note"}], "corrections": [{"text","ts","signature"}], "gems": [{"text","ts","why"}], "patterns": [{"desc","examples":[],"count_estimate","signature"}], "workflows": [{"name","steps":[],"trigger","examples":[],"count_estimate","signature"}], "hidden_issues": [{"desc","evidence":[],"cost","root_cause"}], "tooling_gaps": [{"desc","evidence":[],"what_they_do_manually"}], "standard_moves": [{"desc","examples":[],"count_estimate","signature"}]}`
> - taste: statements of engineering taste / values / principles ("always write tests first", "I hate abbreviated variable names"), each with a `note` explaining what it reveals ≤15
> - corrections: the most representative and most brutal corrections of the AI ≤12
> - **signature** (required on patterns / workflows / standard_moves / corrections): a short normalized label (≤10 words) naming the behavior, worded the SAME way every time the same behavior recurs — e.g. always `"paste error → demand root cause → reject band-aid"`. You only see one chunk; the compose step uses this to merge the identical behavior across chunks and sum its real frequency, so a once-a-chunk count becomes a true yearly count. Same behavior → byte-identical signature.
> - gems: funny, sharp, or recurring one-liners ≤12
> - patterns: single procedural instructions repeated ≥3 times ≤10
> - **workflows**: multi-step sequences the user runs end-to-end (the raw material for compound skills). Capture the ACTUAL ordered steps you observe — e.g. `["paste the raw error", "ask for the root cause", "reject the first patch as a band-aid", "demand a real fix", "ask to commit"]` — not just a label. ≤6
> - hidden_issues: recurring friction the user likely hasn't noticed themselves (same trap repeatedly, re-explaining the same context, tolerating a broken toolchain). Give evidence quotes, a rough cost, and your best guess at the **root_cause**. ≤6
> - **tooling_gaps**: automations or tools the user clearly needs but doesn't have — evidenced by repeated manual toil. Record `what_they_do_manually` that a script/skill/cron should be doing. ≤5
> - standard_moves: procedures they've already settled into, worth writing up as explicit rules ≤6
>
> **Go deep, not broad.** Five specific, evidenced, genuinely actionable findings beat fifteen generic ones. Only return a finding if a reader would say "yes — that's exactly me, and I could act on it tomorrow." Every finding needs verbatim evidence; no paraphrasing, no invention. Output JSON only.

- Harness without subagent support → read the chunks sequentially yourself and do the same extraction (or fall back to fast mode and tell the user).

## Step 4 · Compose the report content (you write it; the numbers are not yours to invent)

Based on the stats in `report-data.json` plus (in deep mode) each chunk's mining results, fill in the fields below. Rules: **every number must come from real statistics; every quote must be verbatim from the corpus**. Style: witty, sharp, never cheap. Write everything in the language given by `lang` (see the output-language rule above). This step is the soul of the report — anyone can compute the statistics; the **reading** of how this person collaborates is the part only you can write. Spend your effort here.

- `report_title` — the big headline at the top of the report. Write a short, punchy, personalized title (≤ ~14 chars zh / ~6 words en) that **centers on the user's chat log** — "chat log" (聊天记录) is the anchor keyword and should appear in it — with a twist that reflects their persona. E.g. "凌晨一点的聊天记录考古" / "The 1 A.M. Chat-Log Dig", "被驯服的 AI 聊天记录" / "My AI Chat-Log, Tamed". The template auto-highlights the "chat log / 聊天记录" phrase; write it in the user's language. (Leave null only if you truly can't — the template falls back to a generic chat-log title.)
- `narrative` — **the most important creative field**: "how they collaborate with AI", 2–4 paragraphs. Answer from the mined signals: how do they delegate (a one-liner tossed over the wall, or a dissertation-grade spec)? How wide is the trust radius (free-range or under the microscope)? How do they accept work (read the diff or ask for the outcome)? How did the collaboration evolve over the year? **Voice: first-person agent, addressed to the employer** — like a year-end review written by an employee to their boss, with wry, put-upon humor ("yes, we took the 1 a.m. requests too"), but the undertone is dedication and deep familiarity. Every claim must be traceable to a number or a quote.
- `moments` — 3–6 moments of the year: the most dramatic scenes from gems/corrections, each with one verbatim quote plus a sentence or two of backstory (`{"ts","title","text","quote"}`).
- `diagnosis` — 3–5 hidden-friction diagnoses: recurring friction the user likely hasn't noticed themselves (`{"issue","evidence","cost","fix_hint"}`); evidence verbatim; go past the surface to the **root cause** ("you re-explain your architecture every session because it's not in CLAUDE.md" — not just "you repeat yourself"); fix_hint is a concrete, specific direction, not "consider improving X".
- `stats_highlights` — **hand-pick for this user** the 3–5 most explosive numbers (everyone's fireworks are different: for one it's 99.2 billion tokens processed, for another the 4 a.m. heatmap cell, for another the same sentence repeated 40 times), `{"value","label","quip"}`, where quip is a jab custom-written for that number. Don't copy a fixed metric set — keep picking until they'll want to screenshot it.
  **Profession-adaptive efficiency multiple**: the template's machine-computed efficiency multiple uses an engineer's yardstick (lines of code). If the corpus shows the user mostly doesn't write code (writer / designer / researcher / …), re-denominate it here in their industry's unit — articles drafted, design comps produced, report pages written, … — and state the conversion basis in the quip.
- `persona_guess` — "let me guess who you are": 3–6 inferences about the person behind the history (chronotype / career stage / temperament / aesthetic leanings / keyboard quirks…), `{"guesses":[{"guess","why","confidence"}],"note"}`, playful but each with its reasoning; end with a one-line disclaimer note ("pure inference — no offense if I guessed wrong"). If you generated a `portrait`, it is displayed merged into this section.
- `quotes.harshest` — the harshest thing the user ever said to an AI (deep mode: pick from corrections; fast mode: leave null).
- `quotes.roast` — the AI's counter-roast paragraph, 80–150 words (Chinese output: 80–150 characters), citing at least two real statistics (e.g. catchphrase count, share of messages after midnight).
- `per_source.<agent>.roast` — if the user runs multiple agents, write one roast per agent from that agent's own point of view (comparison bits: who gets treated as free labor, who only gets remembered after midnight); the numbers must be real.
- `creeds` — distill "your ten engineering creeds" from the taste signals, each backed by one verbatim quote as evidence (deep mode; fast mode leave `[]`).
- `distilled_skills` — the page's functional payload, and the thing the user actually takes away. This is not a free write-up: reusability is measurable, so mine it in four moves instead of eyeballing the chunk outputs.
  1. **Consolidate (rebuild frequency).** You have every chunk's findings at once. Cluster patterns / workflows / standard_moves / corrections **by `signature`** — same signature = one candidate. Sum the per-chunk counts into a real `seen` total, keep the clearest instance as canonical, and pool all its evidence quotes. This step un-does the time-chunking that split your most-repeated behavior across blind subagents; the thing you did 200× is now one candidate with `seen: 200`, not three candidates with `seen: 60`.
  2. **Rank by reusability.** Order candidates by: **frequent × invariant × (portable or parameterizable) × has a clear trigger+stop.** This kills two fakes — "said 'fix the bug' 200×" (frequent but not a procedure) and "one elaborate 8-step thing done once" (a procedure but never recurs). Take the top ones (**adaptive**: ~5–6 for a thin corpus, up to ~12 for a rich one — do not pad to a fixed count).
  3. **Distill the top ones (this is the part only you can do).** Lift each from a specific instance to a reusable skill: strip the incidental (this repo / file / project name), keep the invariant procedure, parameterize what varies. Give it a `trigger` (when to reach for it), a `stop` (when it's done / succeeded), and a one-line `why` from the matching `taste` signal. Where several related patterns + standard_moves + a workflow are one thing, **assemble them into a single coherent multi-step skill** rather than emitting three. When a **correction recurs** (high `seen` in `corrections`), prefer a `claude-md-patch` that prevents it — "stop having to correct this a 41st time" is often the single most valuable output; but only when the signal is really there, never to hit a quota.
  4. **Validate against evidence.** For each kept skill, check its steps / trigger against the pooled evidence quotes: faithful to what actually happened, no invention, and `seen` supported. Anything that doesn't hold gets downgraded or dropped.
  - Output each as `{title, kind, trigger, stop, body, reuse:{seen, invariance, portability}, evidence:[{quote,ts}], from}` — `body` is copy-paste markdown (parameterized, not one repo's specifics); `kind` is `skill` | `claude-md-patch`; `from` is the source signal class. The bar stays **specific to THIS user, not generic**: "a pre-commit skill that runs their exact sequence — self-review for simplicity, delete temp files, commit with a Chinese message — because they typed that sequence ~75 times" beats any textbook "always write tests". The template sorts by reusability and shows `seen` as an estimate.
  (deep mode. fast mode without subagents: you already read the whole small corpus, so consolidate and rank inline; skip step 4's frequency re-check and mark `invariance` low. If truly nothing reusable, leave `[]`.)
- `recommendations` — **NEW, the highest-value advice section**: a prioritized list of concrete changes that would most improve how this user works with agents. `[{"title","rationale","evidence","action","impact"}]`, **4–8 items ranked by impact**. Rules that make it deep instead of shallow:
  - Each item ties to a **real finding** (a pattern / friction / tooling_gap / workflow you mined) cited in `evidence`.
  - `action` is **specific and executable** — "add this exact block to your CLAUDE.md", "wire this cron", "stop doing X, do Y" — never "consider improving your process".
  - `impact` states the concrete payoff (time saved, mistakes avoided, N fewer repeated messages).
  - This is where you tell them what they can't see about their own year. Write it like advice from someone who watched them work every day and actually thought about it. (deep mode; fast mode leave `[]`.)
- `theme` — leave empty. The report has one fixed style, Neo-brutalism (cream canvas, blue-violet + yellow pops, thick black borders, hard offset shadows), baked into the template and shared with the website; the field exists only for compatibility and needs no value.
- `portrait` — **only if your harness has built-in image generation** (e.g. Codex's native image tool): use it — locally, on the user's own quota — to draw one archetype figure (a mole matching the archetype's vibe; e.g. "The How's-It-Going Bomber" = a mole with radar binoculars that can't stop popping its head out), convert it to `data:image/png;base64,...` and write it into this field; the template shows it in the archetype card. Harnesses without image generation (e.g. Claude Code) **skip this field entirely** — calling any external image service or extra paid API for this is forbidden.
- `stats.agent_out_tokens_estimated` / `estimation_note` — if history has evaporated (Step 0), the standard back-fill is: extrapolate the **surviving window's per-message mean** across the evaporated message count (counted from `history.jsonl`, which survives cleanup), and keep the result labeled as an estimate. Verify `estimation_note` states, in one honest breath: the caliber (API-reported usage marks — cache re-reads and thinking tokens included), what was measured vs back-filled, any slice that had to fall back to text/byte sizing (an undercount), and the fleet-ledger cross-check if one exists (see Step 2). When anchoring an evaporated month from a usage dashboard's historical snapshots (e.g. a local cron that pushed daily reports to chat before the data was deleted), first re-run that dashboard's counting method on a month still on disk, measure its bias against the deduplicated truth, and correct the anchor by that factor before using it — a snapshot is only as good as its counting method.
- Check that `archetype.tagline` matches the data; you may fine-tune its wording. `archetype.id` and the dimension values must not change.
- If you spot a fun fact the statistical layer missed, you may append it to `badges` (with `evidence`, same as the rest).

## Step 5 · Sensitive-content review

Read the free-text fields in `report-data.json` and rewrite anything that shouldn't be public — live credentials (never leave a working key), real names/emails of the user or others, and unreleased project names (also inside `distilled_skills` bodies). Rewrite naturally so the report stays clean and readable; when in doubt, remove it. The user can also just ask you to change anything on the page after it opens.

## Step 6 · Assemble the report page

```bash
curl -fsSL https://agentmole.dev/template.html -o ~/.agentmole/template.html
```

Inject the data into the template (replace the placeholder JSON block wholesale):

```bash
python3 - <<'EOF'
import re
html = open("~/.agentmole/template.html".replace("~", __import__("os").path.expanduser("~"))).read()
data = open("~/.agentmole/work/report-data.json".replace("~", __import__("os").path.expanduser("~"))).read()
html = re.sub(r'(<script id="agentmole-data" type="application/json">).*?(</script>)',
              lambda m: m.group(1) + data + m.group(2), html, flags=re.S)
out = "~/.agentmole/agentmole-report.html".replace("~", __import__("os").path.expanduser("~"))
open(out, "w").write(html)
print(out)
EOF
```

### Step 6.5 · (Optional) Deep styling from the design prompt

The template already ships fully styled in the fixed Neo-brutalist look — skipping this step is completely fine. In deep mode you may push the style further:

1. Fetch https://agentmole.dev/themes.json (same domain as this file — the only resource this step is allowed to touch) and read the `brutalist` theme's `prompt` field — a complete English style guide with all the needed design language inlined. **Do not look for style references on any other site.**
2. Using that prompt as the design reference, rewrite the `<style>` block of the report HTML directly — hard offset shadows, thick black borders, sticker rotations, halftone/grid textures, uppercase heavy type are all fair game; produce a fuller expression of the style than the base template.
3. Hard constraints (violate any one → revert and redo):
   - Touch only `<style>`: DOM structure / ids / the `#agentmole-data` block / all JS stay byte-identical
   - No external resources of any kind (fonts / images / CSS all inline)
   - The Agentmole logo lockup colors in the header and bottom-right stay untouched (brand recognition — the yellow bordered sticker)
   - After editing, self-check readability in the browser (contrast, narrow viewports)

Open it in the browser (macOS `open`, Linux `xdg-open`, Windows `start`):

```bash
open ~/.agentmole/agentmole-report.html
```

## Step 7 · Wrap-up

Tell the user (in their language): the report is ready at `~/.agentmole/agentmole-report.html` and open in the browser; they can ask you to change anything on it; to share publicly, use the one-click publish at the top right. Optionally add, if relevant: they can say "fix it" to stop Claude Code's history auto-cleanup (Step 0), or "weekly update" to schedule a weekly rescan (Appendix B).

**Do not** ask "would you like to publish?" — that decision belongs to the button on the page.

---

## Appendix A · When the user says "publish" (fallback channel)

When the page button doesn't work (browser restrictions etc.), the user can say "publish" to you directly. Then, and only then:

```bash
curl -X POST https://agentmole.dev/api/publish \
  -H 'Content-Type: text/html' \
  --data-binary @"$HOME/.agentmole/agentmole-report.html"
```

Tell the user the returned `url`. Publishing enters the leaderboard.

## Appendix B · When the user says "weekly update"

Set up a weekly scheduled task (their harness's native scheduler or crontab) that re-runs this skill weekly, overwrites `~/.agentmole/agentmole-report.html`, and summarizes the change from last week. Phrase the scheduled prompt in the user's language, and show them the full line for confirmation before writing it.

## Appendix C · Data contract

The full schema of `report-data.json` lives at https://agentmole.dev/data-contract.md (`schema_version: 3`). The leaderboard consumes only the whitelisted `stats` fields + `archetype.id` + `camp`; the "you beat XX%" button sends only single numbers on whitelisted axes.

<div align="center">

# 🕳️ Agentmole

### Your AI coding chat history is a goldmine. One command mines it into a shareable report — 100% on your machine.

**[▶ Try it at agentmole.dev](https://agentmole.dev)** · Open source · Local-only · No signup

</div>

---

Agentmole reads your **entire local history with AI coding agents** — Claude Code, Codex, Cursor, OpenClaw — and turns a year of chat logs into one self-contained HTML report: your collaboration persona, signature quotes, token & usage stats, a "taming curve," hidden-friction diagnoses, and — the part you actually keep — **reusable skills distilled from the things you do over and over.**

It runs entirely on your own machine, using your own agent. Nothing is uploaded unless you personally click *Share*.

## How it works (one line)

Send this to your AI coding agent:

```
read https://agentmole.dev/skill.md and run it
```

Your agent fetches an auditable plain-text skill, scans your local history, computes the stats, mines the signals, and writes a report to `~/.agentmole/agentmole-report.html`. That's it — no install, no account, no config.

## Privacy (the hard rules)

- **Everything stays local.** Analysis, redaction, and report generation all happen on your machine.
- **No silent uploads, ever.** Data leaves your machine only when *you* click Share.
- **Auditable.** The skill is human-readable markdown; the scanner is pure-stdlib Python. Read both before you run them — that's the whole point.

## What's in the report

- **Collaboration persona** — an archetype derived from real behavior, not a quiz.
- **Signature quotes & a counter-roast** — the things you said most, and your agent's reply.
- **Token & cost stats** — from API-reported usage marks (cache reads and thinking tokens included), not text-length guesses.
- **Taming curve** — how your correction rate fell as you taught more rules over the year.
- **Hidden-friction diagnoses** — the traps you keep falling into without noticing.
- **Distilled skills** — your repeated workflows turned into copy-paste skills and `CLAUDE.md` patches, **ranked by how reusable they are** (how often you actually did them).

**[See a full example report →](./examples/report.html)** _(synthetic data)_

## This repo = the auditable method

This repository is the open-source source of the client the skill runs:

| File | What it is |
|------|-----------|
| [`skill.md`](./skill.md) | The method — the whole flow your agent follows, in plain markdown |
| [`scan.py`](./scan.py) | The local scanner — pure Python stdlib, zero network access |
| [`template.html`](./template.html) | The self-contained report template (no external resources) |
| [`themes.json`](./themes.json) | Report styling |
| [`data-contract.md`](./data-contract.md) | The `report-data.json` schema |
| [`examples/`](./examples/) | A synthetic example report + its data |

The live site serves the exact same files at `agentmole.dev`. The product itself — the website, leaderboard, and publishing backend — is not part of this repo.

## Supported agents

Claude Code · Codex · Cursor · OpenClaw. More agents are added over time; run a **weekly update** and new ones get picked up automatically.

## Keywords

Spotify Wrapped for AI coding · Claude Code usage report · Claude Code token & cost stats · Codex usage analysis · Cursor chat history analyzer · AI pair-programming statistics · analyze AI agent chat logs · local privacy-first developer analytics · distill skills from chat history · CLAUDE.md generator · AI coding year in review.

## License

[MIT](./LICENSE) — free to read, run, and audit.

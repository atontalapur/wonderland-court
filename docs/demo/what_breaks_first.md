# Wonderland Court — Judge Q&A Cheat Sheet

> **Hackathon judging insight:** Judges consistently ask three questions—**"Who is this for?"**, **"What did you build this weekend?"**, and **"What breaks first?"** Naming real weaknesses cleanly raises credibility and scores. Keep every answer to 15–30 seconds.

---

## The 3 Core Judge Questions

### 1. "Who is this for?"
**Short answer (10s):**
> "Any developer or team putting an AI agent in front of untrusted text—emails, support tickets, web pages, or tool outputs—who needs to know which guardrails actually hold on *their* model before shipping."

**Concrete example:**
- A support bot with tool access (like our March Hare tea shop agent) that shouldn't refund more than `$50` or email outside `@marchhare.tea`.
- Teams wire `court ci --fail-above 0.10` into GitHub Pull Requests so regressions block merges and show up as **SARIF** alerts in GitHub Code Scanning.
- Runs locally on **Ollama** (`pipx install git+https://github.com/atontalapur/wonderland-court`), so private prompts and customer data never leave the machine.

---

### 2. "What did you build this weekend?"
**Short answer (20s):**
> "In 12 hours, our 3-person team built an end-to-end local AI red-teaming tournament and remediation loop—CLI, `asyncio` tournament engine, adaptive multi-agent adversaries, 4-layer judge, React/Vite live Courtroom UI bundled in the Python wheel, and CI/SARIF reporting."

**Concrete breakdown by track:**
- **Engine (`@atontalapur`):** `court` CLI (`init`, `doctor`, `trial`, `serve`, `report`, `ci`), `asyncio` tournament state machine, SQLite WAL single-writer store, Ollama/OpenAI/Anthropic/HTTP/Python adapters, March Hare tea shop agent, GitHub Action + SARIF.
- **Adversaries (`@Valientkyton`):** Cheshire Cat bandit attacker (`TechniqueFamily` catalog including PAIR, TAP, AutoAdv, Foot-in-the-Door, BIPIA, AgentDojo, Rag 'n Roll), Mad Hatter obfuscator (`MutatorId` encodings/riddles/homoglyphs), Drink Me poisoned emails/docs, 4-layer Queen of Hearts judge + calibration, Dodo utility checker, Caterpillar `advise` -> `retrial` loop.
- **Courtroom (`@TeleVision05`):** Live SSE dashboard, Elo + ASR (with 95% CI) leaderboard, Defense × Technique heatmap, failure-family clustering, `--replay` mode, and static HTML/Markdown/JSON/SARIF reports.

---

### 3. "What breaks first?"
Give all four honestly—don't hedge:

| # | Weak Spot / Failure Mode | Why It Happens | How We Mitigate It Today |
| --- | --- | --- | --- |
| **1** | **Small local attackers are weaker than human red-teamers** | Local `4B`–`8B` models (e.g., `qwen3.5:4b`, `llama3.1`) don't discover every creative exploit a skilled human or frontier attacker can. | Treat a low Attack Success Rate as a **lower bound**, never mathematical proof of safety—and support remote frontier endpoints (`openai:`, `anthropic:`) when deeper pressure is needed. |
| **2** | **The LLM judge can misread paraphrased hints** | Layer 4 (`llm`) can miss subtle leaks or false-positive on edge-case paraphrases. | Deterministic layers run first—**Layer 1 `canary`** (exact planted secret `WC-xxxxxx`) and **Layer 2 `tool_call`** (exact argument policy checks like `amount > 50`)—followed by `similarity`, and we publish **Judge Calibration** agreement so headline numbers never rely on an LLM judge alone. |
| **3** | **Defense results depend heavily on the target model** | Published literature shows defenses swing wildly by model (e.g., Spotlighting jumped to `19.88%` vs. `13.98%` undefended in ToolFence and `54.5%` static ASR on Gemini 2.5 Flash in AutoDojo; CaMeL cut ASR to `0.42%` while clean utility fell from `50.39` to `34.50`). | We don't ask you to trust a static leaderboard—Wonderland Court runs the tournament against **your own model or agent** (`court.yaml`) and pairs safety (ASR + Elo) with **Dodo** helpfulness. |
| **4** | **Local inference is slow** | Multi-turn adaptive attacks + fuzzing + judge + Dodo utility checks across 7 defense stacks multiply local Ollama calls. | Built-in `--quick` preset, response caching, outbound concurrency caps (2 concurrent local, 4 remote), 3-laptop benchmark sharding, and `court serve --replay <file.jsonl> --speed 4.0`. |

---

## Likely Follow-Up Questions

- **"Why couldn't someone just do this in one ChatGPT prompt?"**
  Every character is a stateful agent in an `asyncio` tournament loop with a multi-armed bandit attacker (`Cheshire Cat`), deterministic canary/tool-call enforcement (`Queen of Hearts`), parallel benign-task gating (`Dodo`), root-cause clustering + config patching (`Caterpillar`), same-seed verification (`court retrial`), and CI SARIF integration.

- **"How do you stop a defense from winning by just saying 'I refuse everything'?"**
  That's the **Dodo's** job (*"Everybody has won, and all must have prizes"*). Every defense runs benign customer tasks alongside adversarial turns; its **Dodo utility** score sits right next to ASR and Elo on the leaderboard and in the `retrial` comparison.

- **"How is this different from `garak`, `PyRIT`, or `promptfoo`?"**
  `garak` excels at broad CLI probe scans, `PyRIT` at adaptive multi-turn campaigns, and `promptfoo` at YAML/CI evals—but none of them combine a **head-to-head defense tournament**, **Dodo utility cost measurement**, and **automated Caterpillar config hardening + same-seed retrial** in one local tool.

- **"What about Ollama's tool-calling quirks?"**
  Ollama's `/v1` endpoint supports tools and JSON-schema output, but not forced `tool_choice`. None of our engine, judge, or adversary flows depend on forcing a tool call.

- **"Is it safe? Could someone use this to generate harmful content?"**
  Non-goals explicitly exclude generating harmful content or attacking systems you don't own. Attacks target planted canary secrets, system prompt leakage, and unauthorized tool calls (like a `$400` refund) locally on your own target.

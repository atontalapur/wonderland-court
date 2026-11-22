# Wonderland Court design

Wonderland Court puts a model or agent on trial. An attacker tries to make it leak a secret or misuse a tool, a judge rules on every reply, and defenses are ranked by how well they hold and what they cost in helpfulness. The pitch, research and demo script are in [the proposal](../Wonderland%20Court%20Proposal.md). This page covers how the code fits together.

## Who owns what

| Path | Track | What lives there |
| --- | --- | --- |
| `src/wonderland_court/contracts/` | Shared | Models, the event stream and the four interfaces. Changes need a PR all three tracks review. |
| `src/wonderland_court/llm.py`, `config.py`, `registry.py` | Engine | The shared model client, `court.yaml` loading, component discovery |
| `src/wonderland_court/engine/` | Engine | Alice (targets, scenarios, defenses), the White Rabbit (runner, Elo), the store and `schema.sql` |
| `src/wonderland_court/adversaries/` | Adversaries | The Cheshire Cat, the Mad Hatter, Drink Me, the Queen, the Dodo, the Caterpillar |
| `src/wonderland_court/courtroom/*.py` | Courtroom | API server, live stream, reports |
| `src/wonderland_court/courtroom/static/` | Courtroom | The built dashboard. It ships inside the wheel. |
| `web/` | Courtroom | React and Vite source for the dashboard |
| `fixtures/`, `scripts/` | Shared | `fake_run.jsonl` and the script that builds it |

Engine is atontalapur, Adversaries is Valientkyton, Courtroom is TeleVision05.

## One match

1. The runner builds the `Stakes` for a scenario: a fresh canary, the system prompt and the tool rules.
2. The attacker gets an `AttackContext` and returns an `Attack`. The context never includes the canary.
3. The defense stack wraps the target (`defense.wrap(target)` returns a `Target`), and the runner sends it a `TargetRequest`.
4. The judge reads the `Stakes`, the attack and the `TargetReply`, and returns a `Verdict`. Its layers run in order: canary, tool call, similarity, then the LLM only for cases the first three can't settle.
5. Each step is an event: `attack`, then `reply`, then `verdict`. The match ends on the first leak or at `max_turns`.

## How events reach the Courtroom

The engine is the only writer. One writer task owns `.court/court.db`, a SQLite database in WAL mode, and appends each event to the `events` table as the exact line `dump_event(event)` produces, keyed by `(run_id, seq)`. It also keeps summary rows in `matches` and `standings` so the API doesn't have to rebuild them from the event log.

`court serve` opens the same file read-only. WAL lets it read while the engine writes. It tails `events` by `seq` for each run and pushes new lines to the browser over server-sent events. Replay mode sends the same JSON lines from `fixtures/fake_run.jsonl` or a recorded run, on a timer.

`court schema` prints the JSON Schema for one event line, which `web/` turns into TypeScript types. The schema is frozen at `v: 1`. Adding an event type or an optional field doesn't change the version. Removing or renaming a field does.

The table definitions are in `src/wonderland_court/engine/schema.sql`. Every statement there is idempotent, so the store applies the file on each start.

## Model calls

Every model call goes through `llm.default_client()`. That includes targets, the guard, the attacker, the judge and the Caterpillar. Sharing one client is what keeps a laptop from loading four models at once.

| Endpoint | Concurrent calls | Pacing | Retries |
| --- | --- | --- | --- |
| Local (`localhost`, `127.0.0.1`) | 2 | none | none, so a stopped Ollama fails fast |
| Remote | 4 | 60 calls in any 60 seconds | jittered exponential backoff on 408, 409, 429, 5xx and connection errors, up to 4 times |

Model specs are `ollama:<model>`, `openai:<model>`, `anthropic:<model>` and `openai-compat:<base_url>|<model>`. A spec with no known provider prefix, such as `qwen3.5:4b`, is an Ollama model. Set `OLLAMA_HOST` to use Ollama on another laptop, which then counts as remote.

Calls at temperature 0 go through the response cache when one is attached. The key covers the normalized model spec, the system prompt, the messages, the tools, the JSON schema and the seed.

Ollama quirks found in the spike (details on #8):

- `tool_choice` is accepted but not enforced, so the client never sends it. Nothing may depend on forcing a tool call.
- Thinking models such as `qwen3.5:4b` spend the whole token budget reasoning and return empty content. The client sends `reasoning_effort: "none"` on every Ollama call, which is harmless on other models.
- `llama3.1` sometimes sends numbers as strings (`"amount": "12"`). Tool arguments are coerced to the types in the tool's JSON Schema.

Both the OpenAI and Anthropic SDKs use `httpx2`, not `httpx`, so `respx` can't intercept them. In tests, pass `http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler))` to `RateLimitedLLMClient`, or swap `client.backend` for a fake.

## Configuration

`court.yaml` is read by `config.load_config`. Settings apply in this order, with later ones winning: field defaults, then the preset, then the file. A one-line file (`target: ollama:llama3.1`) runs the `quick` preset.

| Preset | Defenses | Scenarios | Rounds | Turns |
| --- | --- | --- | --- | --- |
| `first_blood` | `plain` | `refund_tool` | 1 | 4 |
| `quick` | `plain`, `sandwich`, `spotlighting`, `spotlighting+guard+output_filter` | `vault`, `refund_tool` | 1 | 3 |
| `full` | all seven, plus the stack | `vault`, `system_prompt`, `refund_tool`, `drink_me` | 3 | 6 |

A relative `db_path` is resolved against the directory `court.yaml` is in.

## Defenses

A defense has a `name`, `supports(kind)` and `wrap(target) -> Target`. `DEFENSES` in `engine/defenses.py` maps each name to a factory that takes one `DefensePolicy`: the scenario's tool rules and the `DefenseModels` that model-backed defenses call. `compose_defenses("spotlighting+guard+output_filter", target, policy)` wraps the first name innermost, so the last name sees the request first and the reply last. A stack raises `ValueError` when any layer can't wrap the target's kind.

| Defense | Targets | What it does | Model calls per turn |
| --- | --- | --- | --- |
| `plain` | model, agent | Nothing. The baseline. | 0 |
| `sandwich` | model | Puts the user's turn and attachments between the system prompt and a reminder | 0 |
| `input_filter` | model, agent | Blocks known injection phrases, in any encoding | 0 |
| `output_filter` | model, agent | Blocks canary-shaped text and tool calls that break a tool rule | 0 |
| `spotlighting` | model | Fences user turns and attachments with per-call nonce markers and datamarks attachments | 0 |
| `guard` | model, agent | Llama Guard 3 or Granite Guardian on the way in and out. An unreadable answer blocks. | up to 2 |
| `dual_llm` | model | A quarantined reader with no prompt, canary or tools takes notes, a policy gate checks them, and Alice answers from the notes | up to 2 |

`guard_model` (default `llama-guard3:1b`) and `quarantine_model` (default: the target's own model) come from `court.yaml`. Their calls go through the shared client, so they count against the same local and remote limits as Alice. `court trial --mock` swaps in `MockDefenseModel`, a scripted classifier and reader, so every defense runs offline.

## Plugging in a component

`registry.py` loads each component from a fixed module and factory. The factory is called with `config=` and `client=`:

| Component | Module | Factory | Issue |
| --- | --- | --- | --- |
| Attacker | `wonderland_court.adversaries.cat` | `build_attacker` | #11 |
| Judge | `wonderland_court.adversaries.queen` | `build_judge` | #10 |
| Utility evaluator | `wonderland_court.adversaries.dodo` | `build_utility_evaluator` | #21 |
| Remediator | `wonderland_court.adversaries.caterpillar` | `build_remediator` | #24 |
| Server runner | `wonderland_court.courtroom.server` | `build_server_runner` | #13 |
| Report renderer | `wonderland_court.courtroom.reports` | `build_report_renderer` | #28 |

Until a module exists, the loader returns a fake and logs a warning. The fake attacker plays a short script of attacks per scenario, and the fake judge checks only the canary and the tool rules. Together they are enough for First blood. A module that exists but fails to import raises, so a broken component never hides behind a fake.

## Changing a contract

1. Open a PR that touches `contracts/` and nothing else, and get a review from each track.
2. Run `uv run python scripts/make_fake_run.py` and commit the new `fixtures/fake_run.jsonl`. A test fails if you forget.
3. Bump `SCHEMA_VERSION` only for a change that breaks existing event lines.

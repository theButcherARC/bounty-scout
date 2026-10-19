# Bounty Scout

A small, working AI agent built with the **OpenMinion 0.1 Python SDK** for
**Cortensor Hackathon #5**.

Bounty Scout evaluates a crypto bounty/hackathon listing and produces a
structured fit report for a solo builder profile: payout, deadline, effort
estimate, and an honest 1-5 fit score. No hype, weak listings get low scores.

## How it works

```
listing URL
    |
    v
fetch page text (plain Python, deterministic, zero model calls)
    |
    v
fact-extractor (bounded subagent, typed output: BountyFacts)
    |
    v
bounty-scout (main agent, typed output: FitReport)
    |  scores against the builder profile, session remembers past runs
    v
reports/<listing>.md
```

- **Delegation:** the main agent spawns a bounded `subagent()` child with its
  own instructions, Pydantic `output_type`, and a 240s timeout. The child does
  one focused job: turn page text into validated `BountyFacts`.
- **Typed outputs:** `BountyFacts` and `FitReport` are Pydantic models, so the
  report shape is guaranteed; invalid model replies raise and are retried.
- **Sessions:** `session_id="bounty-scout"` persists evaluation history in the
  local OpenMinion state DB; ask "what did we evaluate before?" in a later run.
- **Tools & permissions:** `fetch_page` is declared `idempotent` with
  `min_scope="network:read"`. The page fetch itself runs in plain Python for
  determinism (free-tier endpoints rate-limit multi-turn tool loops); the tool
  stays registered for live use. File writes stay in plain Python, outside the
  model loop, so the model can never write arbitrary files.

## Setup

Requires Python 3.11+.

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install "openminion==0.1.1"
```

Configure a model provider. Any OpenAI-compatible endpoint works:

```bash
# Free, no key needed (1 request / 30s):
export OPENAI_COMPATIBLE_API_KEY="none"
openminion setup --no-chat --provider custom-openai-compatible \
  --api-format openai-compatible --base-url https://text.pollinations.ai/openai \
  --model openai
```

Or use your own key with OpenAI / OpenRouter / Ollama (see
`openminion setup --help`). Clear IPv6 entries from `no_proxy` if your
HTTP client chokes on them (the script does this itself).

Verify the provider:

```bash
openminion doctor --check-turn
```

## Run

```bash
# uses the default example listing
python scout.py

# evaluate any listing URL
python scout.py https://superteam.fun/earn/listing/<slug>

# override the model
python scout.py --model="openai:gpt-4o-mini" <url>
```

Output: a `FitReport` printed to the console and saved as
`reports/<listing>.md`.

Example:

```
SCORE 3/5 - Decent content bounty, crowded field
```

## Project layout

```
scout.py        # agent: tools, subagent delegation, typed outputs, CLI
reports/        # generated fit reports (created on first run)
.openminion/    # local SDK config + session state (git-ignored)
```

## Building blocks tested

- **Agent execution** - `Agent` context manager + `run()`; works as documented.
- **Models** - `model="provider:model"` override works; custom
  OpenAI-compatible endpoints work via `openminion setup`.
- **Tools** - `@tool` with `idempotent` / `min_scope` works; the model called
  `fetch_page` correctly on the first try.
- **Permissions** - read-only tool scopes behave; write actions kept out of the
  model loop by design.
- **Sessions** - `session_id` persists across runs in the local state DB.
- **Memory** - profile instructions persist; session recalls past evaluations.
- **Delegation** - `subagent(parent, ...)` with `output_type` + `timeout_seconds`
  works; the child returned validated `BountyFacts`.
- **Diagnostics** - `openminion doctor --check-turn` verified the provider.
- **Typed outputs** - Pydantic `output_type` enforced; invalid replies raise
  `AgentOutputValidationError` (caught and retried).

## What we learned

- Provider failures surface in two ways: an error-text reply
  ("openminion: The configured model provider failed...") or an
  `AgentOutputValidationError` when the error text can't coerce to the
  `output_type`. Client code should handle both and back off.
- The SDK's httpx transport fails on IPv6 entries in `no_proxy`
  (`InvalidURL: Invalid port: ':1]'`). Clearing `no_proxy`/`NO_PROXY` fixed it.
  Worth handling or documenting in the SDK.
- Free-tier hosted endpoints (1 req / 30s) make multi-turn tool loops slow;
  a client-side retry with 35s backoff was enough for this demo.
- Small quality-of-life ask: a `--provider` echo of the *effective* base URL
  in `openminion config show` already exists and helped debugging a lot.

## License

MIT

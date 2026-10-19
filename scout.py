#!/usr/bin/env python3
"""Bounty Scout - Cortensor Hackathon #5 submission.

An OpenMinion 0.1 agent that evaluates crypto bounties/hackathons for a
vibe-coder profile and writes a structured fit report.

Building blocks exercised:
  - agent execution (Agent context manager + run)
  - models (configurable provider; model="provider:model" override)
  - tools (fetch_page: read-only, idempotent, min_scope network:read;
    page fetch done in Python for determinism, tool registered for live use)
  - permissions (tool scopes; writes stay in Python, outside the model loop)
  - sessions (session_id="bounty-scout" persists history in .openminion/state)
  - memory (profile baked into instructions; session recalls past evaluations)
  - delegation (bounded fact-extractor subagent with typed output + timeout)
  - diagnostics (openminion doctor --check-turn)
  - typed outputs (Pydantic BountyFacts / FitReport)
"""

from __future__ import annotations

import os
import re
import sys
import time
import urllib.request
from pathlib import Path

# The SDK talks to the local proxy on 127.0.0.1:8081 (see openrouter_proxy.py).
# httpx chokes on IPv6 entries in the system no_proxy ("Invalid port: ':1]'),
# so override no_proxy with ONLY localhost entries (no IPv6). Page fetch still
# uses https_proxy for internet; localhost bypasses it.
os.environ["no_proxy"] = "localhost,127.0.0.1"
os.environ["NO_PROXY"] = "localhost,127.0.0.1"

from pydantic import BaseModel, Field

from openminion import Agent, ProviderError, subagent, tool

MODEL = "openai:cohere/north-mini-code:free"  # via local proxy -> OpenRouter (free tier), see openrouter_proxy.py

PROFILE = (
    "Haroon is a vibe coder: builds with AI assistance, NOT a professional engineer. "
    "Strong: React, AI-integrated apps, X threads/videos, crypto trading knowledge. "
    "Weak: deep debugging, security audits, complex full-stack builds. "
    "Prefers small bounties ($200-$2,000), content bounties, simple dev tasks. "
    "Skips audit contests, region-locked listings, complex $5k+ builds."
)


class BountyFacts(BaseModel):
    """Facts extracted from a listing page. Never invented."""

    name: str = Field(description="Exact listing name")
    payout: str = Field(description="Payout amount and currency")
    deadline: str = Field(description="Submission deadline as stated, or 'unknown'")
    skills: str = Field(description="Required skills")
    region: str = Field(description="Eligibility / region restrictions, or 'Global'")


class FitReport(BaseModel):
    """Final scored report."""

    name: str
    payout: str
    deadline: str
    effort_hours: str = Field(description="Estimated hours for Haroon, e.g. '3-4'")
    fit_score: int = Field(ge=1, le=5, description="1=skip, 5=do it now")
    verdict: str = Field(description="One-line verdict, plain words")
    reasoning: str = Field(description="2-3 honest sentences, no hype")


@tool(
    idempotent=True,
    min_scope="network:read",
    description="Fetch a URL and return its visible text (max 6000 chars). Read-only.",
)
def fetch_page(url: str) -> str:
    """Fetch a URL and return visible text. Also usable as a plain function."""
    return _fetch_page_text(url)


def _fetch_page_text(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "BountyScout/0.1"})
    with urllib.request.urlopen(req, timeout=25) as resp:
        raw = resp.read().decode("utf-8", "replace")
    text = re.sub(r"<script.*?</script>", " ", raw, flags=re.S | re.I)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text)[:6000]


def save_report_md(report: FitReport) -> Path:
    out = Path("reports")
    out.mkdir(exist_ok=True)
    safe = "".join(c for c in report.name.lower() if c.isalnum() or c in "-_")[:50] or "report"
    path = out / f"{safe}.md"
    path.write_text(
        f"# {report.name}\n\n"
        f"- **Payout:** {report.payout}\n"
        f"- **Deadline:** {report.deadline}\n"
        f"- **Effort:** {report.effort_hours} hours\n"
        f"- **Fit score:** {report.fit_score}/5\n"
        f"- **Verdict:** {report.verdict}\n\n"
        f"## Reasoning\n{report.reasoning}\n",
        encoding="utf-8",
    )
    return path


def run_with_retry(agent: Agent, prompt: str, retries: int = 4):
    """Run with backoff for the free-tier rate limit.

    Provider failures surface either as an error-text reply or as an
    output-coercion exception, so both paths retry.
    """
    last_exc = None
    for i in range(retries):
        try:
            res = agent.run(prompt)
            if res.text.startswith("openminion: The configured model provider failed"):
                raise RuntimeError("provider error text: " + res.text[:200])
            return res
        except Exception as exc:  # noqa: BLE001 - retry on any transient failure
            last_exc = exc
            wait = 60
            print(f"  [attempt {i + 1}/{retries} failed: {str(exc)[:120]}, waiting {wait}s...]", flush=True)
            time.sleep(wait)
    raise last_exc


def main() -> None:
    model = MODEL
    args = [a for a in sys.argv[1:] if not a.startswith("--model=")]
    for a in sys.argv[1:]:
        if a.startswith("--model="):
            model = a.split("=", 1)[1]
    target = args[0] if args else (
        "https://superteam.fun/earn/listing/create-content-on-premier-league-predictions-with-worm"
    )

    try:
        with Agent(
            name="bounty-scout",
            instructions=(
                "You are Bounty Scout, an evaluator for crypto bounties and hackathons. "
                "You receive listing facts and score them honestly for the user profile below. "
                "No hype, no fake confidence. A weak listing gets a low score, said plainly. "
                "When asked for a FitReport, output ONLY raw JSON, no markdown, no explanation.\n\n"
                f"USER PROFILE: {PROFILE}"
            ),
            model=model,
            session_id="bounty-scout",
            output_type=FitReport,
        ) as scout:
            # The page is fetched in Python (deterministic, no model calls spent).
            # The subagent + main agent each make exactly one model call.
            print("[1/3] fetching listing page...")
            page_text = _fetch_page_text(target)[:3000]  # keep prompt small for the local model
            print(f"  got {len(page_text)} chars")

            extractor = subagent(
                parent=scout,
                name="fact-extractor",
                instructions=(
                    "Output ONLY raw JSON, no markdown fences, no explanation, no other text. "
                    "Do NOT wrap in any outer key. Output the flat object directly. "
                    "Extract from the listing text with EXACTLY these keys: "
                    "name (string, exact listing name), "
                    "payout (string, amount and currency), "
                    "deadline (string, as stated or 'unknown'), "
                    "skills (string, required skills), "
                    "region (string, eligibility or 'Global'). "
                    "Use 'unknown' for anything not stated. Never invent numbers."
                ),
                output_type=BountyFacts,
                timeout_seconds=240,
            )
            print("[2/3] extractor: extracting facts...")
            facts_res = run_with_retry(
                extractor, "Extract BountyFacts from this listing text:\n\n" + page_text
            )
            facts: BountyFacts = facts_res.output
            print("facts:", facts.model_dump_json()[:500])

            print("  (waiting 30s before scoring to respect rate limits...)")
            time.sleep(30)
            print("[3/3] scout: scoring fit...")
            score_res = run_with_retry(
                scout,
                "Output ONLY raw JSON, no markdown, no wrapper key. Output the flat "
                "object directly with EXACTLY these keys: "
                "name (string, listing name), "
                "payout (string, amount and currency), "
                "deadline (string), "
                "effort_hours (string, e.g. '3-4'), "
                "fit_score (integer 1-5, 1=skip, 5=do it now), "
                "verdict (string, one-line plain verdict), "
                "reasoning (string, 2-3 honest sentences, no hype). "
                "Score honestly for the user profile. Facts:\n"
                + facts.model_dump_json(indent=1),
            )
            report: FitReport = score_res.output

            print("[4/4] saving report...")
            path = save_report_md(report)
            print(f"saved: {path}")
            print(f"\nSCORE {report.fit_score}/5 - {report.verdict}")
    except ProviderError as exc:
        print(f"provider failed: {exc.code}: {exc.message}")
        sys.exit(2)


if __name__ == "__main__":
    main()

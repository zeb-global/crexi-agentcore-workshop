# Checkpoint 5 — live results (reference build)

Same scenario prompt as Checkpoints 1/2, run via invoke-time model override
against the deployed `investorAgent` harness, no redeploy between models.

## Nova Lite (`us.amazon.nova-lite-v1:0`)

**Fails completely, on every tool-calling attempt** — not just the full
underwriting chain, but even the simplest single `get_listing` call:

```
modelStreamErrorException: Model produced invalid sequence as part of ToolUse.
```

Reproduced 3/3 times, across three different prompts (full scenario, a
single lookup, and a plain greeting). The plain greeting with no tool call
required succeeds normally — so this is specifically a tool-calling
incompatibility with this harness's Gateway tool schemas and/or the
Sonnet-tuned system prompt, not a general capability gap.

**This is the finding, not a bug to fix.** It is a stronger, more useful
answer for CREXi's free-tier decision than "Nova is a bit worse": as
configured, Nova Lite cannot be the model behind *any* tool-using agent in
this harness. If CREXi wants a cheap tier, either the tool surface has to
shrink to something Nova can drive, or the free tier has to be a
non-tool-calling experience, or a different cheap model needs evaluating.

## Sonnet 4.6 vs Opus 4.6, same scenario

| Model | Model calls (server-side loop) | Input tokens | Output tokens | Cost* |
|---|---|---|---|---|
| Sonnet 4.6 | 5 | 18,637 | 1,610 | $0.0801 |
| Opus 4.6 | 3 | 8,282 | 1,393 | $0.2287 |

*Standard published Bedrock on-demand rates — confirm against the live
pricing page before the actual event. See `backend/pricing.yaml`.

Opus needed fewer, larger model calls to reach the same correct answer
(3 vs 5) — but at 5x/5x the per-token rate, it still costs **2.9x more**
than Sonnet for this exact scenario, despite using fewer total tokens.
Worth saying out loud in the room: fewer calls does not mean cheaper.

## Answer to "which model should the free tier use"

Neither Nova Lite nor Opus. Nova Lite cannot complete the task at all as
configured; Opus is strictly more expensive than Sonnet for no quality
gain on this scenario (both got the correct answer). Sonnet 4.6 is both
the default and the right choice here — the real product decision this
scenario supports is knowing Opus is the wrong upgrade to reach for by
default, not which of two working options is cheaper.

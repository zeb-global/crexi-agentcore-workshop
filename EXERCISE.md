# Workshop exercise — what you build today

This branch is the **participant exercise version** of the CREXi AgentCore Workshop repo. It
deploys and runs out of the box (`make bootstrap` → `make dev`), but the two agents are dumb
stubs and one write path is unimplemented until you fill them in, checkpoint by checkpoint.

For the full step-by-step guide — what each field means, exactly what to type, and what the
correct answer is — open the workshop walkthrough (`workshop-walkthrough.html`, given out
separately). This file only states the boundary.

## The six files you touch

Everything else in this repo (`agentcore/`, `infra/`, `services/`, `frontend/`) is pre-built —
if a checkpoint seems to require touching one of those, you've misread it; ask a facilitator.

| File | Starts as | Checkpoint |
| --- | --- | --- |
| `app/investorAgent/harness.json` | Stub: name + model only, no tools, no memory | 1, 2 |
| `app/investorAgent/system-prompt.md` | One-line generic placeholder | 1, 2 |
| `app/brokerAgent/harness.json` | Stub: name + model only, no tools, no memory | 3, 4 |
| `app/brokerAgent/system-prompt.md` | One-line generic placeholder | 3, 4 |
| `backend/confirmation.py` | Two functions raise `NotImplementedError` | 4 |
| `backend/pricing.yaml` | Model rates zeroed out | 5 |

## One deliberate deviation from the original scope doc

The scope doc's checkpoint table says "run `agentcore add harness --name broker-agent`" as if
the second harness doesn't exist until Checkpoint 3. In this repo, **both harnesses are already
registered** in `agentcore.json` (as `investorAgent` / `brokerAgent` — note no hyphens: harness
names must match `^[a-zA-Z][a-zA-Z0-9_]{0,39}$`, confirmed against the CLI's own schema) and
both deploy from Checkpoint 0 onward as stubs. This isn't a shortcut — the per-participant
render pipeline (`scripts/render_agentcore_config.py`) renders and deploys both harnesses
together on every `make bootstrap`/`make deploy`, and splitting that so the broker harness
appears only after Checkpoint 3 would mean reworking the two-phase gateway/harness deploy this
repo already has verified working end to end. Checkpoint 3 is still "the second agent, real
isolation" in every way that matters: its `harness.json` is empty until you fill it in.

## Running it

Same as the main README: `make preflight` → `make bootstrap WORKSHOP_ID=… WORKSHOP_SECRET=…` →
`make wire-backend-env WORKSHOP_ID=…` → `make dev`. It deploys and the chat UI responds from
Checkpoint 0 — you're talking to a generic assistant with no tools, no memory, and no
personalization until you build those in.

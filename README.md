# CREXi AgentCore Workshop

**This is the workshop branch.** `make bootstrap` here only deploys the CDK baseline (data, identity, legacy
desk, tool Lambdas, observability) — every AgentCore-native piece (Gateways, harnesses, and the Legacy Portal
OAuth workload identity/credential provider) you build **by hand**, following **[WALKTHROUGH.md](WALKTHROUGH.md)**.
That hands-on work is the actual point of the workshop. If you'd rather see a fully automated one-command deploy
end to end for reference, that's the `reference` branch — not this one.

A live, working reference implementation of two AI assistants for commercial real estate, built on **Amazon
Bedrock AgentCore**:

- **Investor Assistant** — helps investors find and evaluate multi-family listings, retrieves market comps and
  T-12 operating statements, and runs underwriting (cap rate, DSCR, cash-on-cash) via a Code Interpreter tool.
- **Broker Assistant** — helps brokers review their own listings, change asking prices (with a human-in-the-loop
  confirmation step), and look up rent-roll/concessions data in a separate legacy system that has no API, reached
  only through an AgentCore Browser tool driving a real login form.

Every participant gets their **own, fully isolated copy** of this stack in the same AWS account — own harnesses,
own Gateways, own Lambdas, own DynamoDB tables, own Cognito user pool, own legacy-desk instance. Nothing is shared
between participants except the AWS account itself.

## Architecture

```
┌─────────────┐      ┌──────────────────────────────┐      ┌─────────────────────────┐
│   React     │◄────►│   FastAPI backend (AG-UI)     │◄────►│  AgentCore Harness (x2) │
│  frontend   │ SSE  │  Cognito JWT auth, human-in-  │      │  investorAgent          │
│ :5173       │      │  the-loop pause/resume, cost   │      │  brokerAgent            │
└─────────────┘      │  tracking                     │      └───────────┬─────────────┘
                      └──────────────────────────────┘                  │
                                                              ┌──────────┴──────────┐
                                                              │                     │
                                                    ┌─────────▼────────┐  ┌─────────▼─────────┐
                                                    │ AgentCore Gateway │  │  AgentCore Browser │
                                                    │  gw-readonly      │  │  (legacy deal desk │
                                                    │  gw-ops           │  │   login + scrape)  │
                                                    └─────────┬─────────┘  └─────────┬──────────┘
                                                              │                      │
                                                    ┌─────────▼─────────┐  ┌─────────▼──────────┐
                                                    │  Two Lambda MCP    │  │ Legacy deal-desk    │
                                                    │  targets (search,  │  │ Lambda + Function   │
                                                    │  comps, docs,      │  │ URL (its own login  │
                                                    │  price changes)    │  │ form, no API)       │
                                                    └─────────┬──────────┘  └─────────┬───────────┘
                                                              │                       │
                                                    ┌─────────▼───────────────────────▼──────────┐
                                                    │  DynamoDB (listings, approvals, changelog,   │
                                                    │  legacy-creds, legacy-records) + S3 (docs)    │
                                                    └───────────────────────────────────────────────┘
```

Everything above is namespaced by a `WORKSHOP_ID` you choose — the stacks, Lambdas, tables, Cognito pool, harness
names, Gateway names, and even the legacy-desk's own login URL. See [Per-participant isolation](#per-participant-isolation-how-this-actually-works)
below for how that's enforced.

## Prerequisites

| Requirement | Notes |
| --- | --- |
| **Node.js ≥ 20** | `node --version` |
| **Python ≥ 3.12** | `python3 --version`. On a very new macOS release, Homebrew's Python can ship with a broken `pyexpat` extension that breaks `pip` entirely (`ImportError: ... Symbol not found: _XML_SetAllocTrackerActivationThreshold`) — if `pip install` fails with that, `brew reinstall python@3.1x` and re-run; if it recurs, the extension needs re-linking against Homebrew's own `libexpat` (`otool -L`/`install_name_tool`/`codesign --force --sign -`). |
| **AWS CLI v2** | `aws --version` should show `aws-cli/2.x` |
| **AgentCore CLI** | `npm install -g @aws/agentcore`. If `agentcore --version` doesn't print a bare version number, an old `pip install bedrock-agentcore-starter-toolkit` is shadowing it on `PATH` — `pip uninstall` it. |
| **AWS credentials** | Valid, with Bedrock model access to Claude Sonnet 4.6, Claude Opus 4.6, and Nova Lite in your region. If you're on temporary/session credentials, they can expire mid-deploy — re-paste fresh ones and re-run the failed step; every step here is safe to re-run. |
| **Region** | `us-west-2` by default (`AWS_REGION`/`AWS_DEFAULT_REGION` override the Makefile default, and can also silently override an otherwise-correct AWS CLI profile — `make preflight` checks the *effective* region, not just the configured one). |
| **CDK bootstrapped** | `cdk bootstrap` once per account/region, if not already done. |

Run `make preflight` any time to check all of the above at once (it also validates your chosen `WORKSHOP_ID`).

### Adding your AWS credentials

If you were handed **temporary/session credentials** (an access key, secret key, and session token — the common
case for a shared workshop account), export all three in the same terminal you'll run `make` from:

```bash
export AWS_ACCESS_KEY_ID=AKIA...
export AWS_SECRET_ACCESS_KEY=...
export AWS_SESSION_TOKEN=...
```

These are only set for that terminal session — open a new tab/window and you'll need to re-export them there too.
They also expire (sometimes in as little as an hour); if a command suddenly fails with `ExpiredToken` or
`security token included in the request is expired`, get fresh credentials and re-export, then just re-run
whatever step failed — everything in this workshop is safe to retry.

If you were handed a **long-lived access key pair** instead (no session token), either export just the first two
lines above, or run `aws configure` once to store them in `~/.aws/credentials` so you don't need to re-export them
every session.

Either way, confirm they're active before continuing:

```bash
aws sts get-caller-identity
```

This should print your account ID and an ARN, not an error.

## Quickstart

Pick a `WORKSHOP_ID` — a short, lowercase-friendly, **letters-and-digits-only, must start with a letter** name
that's unique to you (e.g. your name or initials + a number: `jsmith01`). Pick a `WORKSHOP_SECRET` too — any string;
it deterministically derives your two test users' passwords (see [Logging in](#logging-in)), so nobody needs to
hand you a password.

```bash
export WORKSHOP_ID=jsmith01
export WORKSHOP_SECRET=some-secret-only-you-know
export AWS_REGION=us-west-2   # or your region

make preflight
make bootstrap WORKSHOP_ID=$WORKSHOP_ID WORKSHOP_SECRET=$WORKSHOP_SECRET
```

On first run, `make bootstrap` also provisions `infra/.venv`, `backend/.venv`, and `frontend/node_modules`, then
deploys 5 CDK stacks (data, identity, legacy desk, tool Lambdas, observability) — **and stops there.** There is no
`agentcore/` or `app/` directory yet at this point; you create both from scratch in WALKTHROUGH.md's Phase 0. Everything after this is manual: open **[WALKTHROUGH.md](WALKTHROUGH.md)** and work through
building the investor harness, the broker harness, and the Legacy Portal OAuth setup by hand. Only once the
walkthrough has you run `make wire-backend-env` does `make dev` (FastAPI backend on `:8000`, Vite frontend on
`:5173`, open **http://localhost:5173**) become meaningful.

### Logging in

Two users are seeded automatically: `dana` (investors group) and `marcus` (brokers group). Their password is
derived from your `WORKSHOP_SECRET` — compute it yourself, it's never stored anywhere:

```bash
python3 -c "
import hashlib
secret = 'some-secret-only-you-know'  # your WORKSHOP_SECRET
for username in ('dana', 'marcus'):
    digest = hashlib.sha256(f'{secret}:{username}'.encode()).hexdigest()
    print(username, f'Wk-{digest[:20]}!9')
"
```

### Things to try

- **As dana (investor):** "What multi-family listings are available in Columbus?", then "Run underwriting on
  `<two of the properties it lists>`, minimum cap rate 6.5%." Watch the tool-activity panel — underwriting should go
  through a real Code Interpreter execution, not the model just typing numbers.
- **As marcus (broker):** "What listings do I have?", then "Change the asking price on `<one of them>` to
  `<a new number>`." — this pauses for your explicit confirmation before writing anything. Also try: "Check the rent
  roll for `<a listing>` on the legacy deal desk" — this drives a real browser session through a separate login-gated
  app with no API.

### Resetting data

If you (or your underwriting/price-change tests) leave the seed data in a messy state:

```bash
make seed WORKSHOP_ID=$WORKSHOP_ID
```

### Tearing down

When you're done, this removes **only your own** resources — nobody else's:

```bash
make destroy WORKSHOP_ID=$WORKSHOP_ID
```

## Per-participant isolation (how this actually works)

This is the part worth understanding if you're going to run more than one `WORKSHOP_ID` in the same account, or if
something looks like it's talking to the wrong data.

**The data layer** (`infra/`, deployed by CDK) was designed to be per-participant from the start: every DynamoDB
table, S3 bucket, Cognito pool, and Lambda function name is literally `crexi-<WORKSHOP_ID>-*`. That part just works.

**The AgentCore harness/gateway layer** is not naturally per-participant — `agentcore deploy` is normally a single,
shared, project-wide deployment. Three real, load-bearing facts this project's tooling works around, all confirmed
by directly inspecting the synthesized CloudFormation template and the CLI's own behavior:

1. **`agentcore deploy --target <id>`** gives each participant an independently tracked CloudFormation stack
   (`AgentCore-crexiWorkshopV2-<id>`) — but every *physical name* inside that stack (Gateway Name, Harness Name, and
   the harness's own IAM Role name) is a literal string, **not** namespaced by the target automatically. Two
   participants both naming a harness literally `investorAgent` would collide on the same IAM Role even in separate
   stacks — **this is why WALKTHROUGH.md has you suffix every resource name you create by hand with your own
   `WORKSHOP_ID`** (e.g. `investorAgent_jsmith01`), not just accept a tool's default suggestion.

2. A harness's Gateway reference (`tools[].config.agentCoreGateway.gatewayArn`) is a **resolved literal ARN**, not
   an in-stack CDK reference — and AWS only assigns that ARN once the Gateway actually exists. This is why
   WALKTHROUGH.md has you create your Gateways *before* the harness that references them, not the other way round.

3. `agentcore validate` derives a harness's config directory from its registry `name` as `app/<name>/harness.json`
   — not the schema's own separate `path` field, so each harness you create by hand needs its own directory
   matching its name. WALKTHROUGH.md's steps handle this as part of `agentcore add harness`/the atomic CLI
   commands.

4. `app/brokerAgent_<id>/system-prompt.md` names the legacy deal desk's Lambda Function URL as literal text, for
   the model to navigate the Browser tool to. That URL is unique per participant (`LegacyStack`'s `LegacyDeskUrl`
   output) — WALKTHROUGH.md has you paste your own into the prompt.

If you ever see a broker harness fail to log into the legacy desk, or an investor harness returning another
participant's listings, one of these four is the first thing to check — it almost certainly means a resource name
or URL was copied from someone else's example instead of your own `WORKSHOP_ID`'s values.

### `make deploy` vs `make bootstrap`

`make bootstrap` only does the CDK baseline. `make deploy WORKSHOP_ID=$WORKSHOP_ID` is a plain passthrough to
`agentcore deploy` for whatever you've built by hand so far — use it after any harness/gateway change per
WALKTHROUGH.md. Run `make wire-backend-env WORKSHOP_ID=$WORKSHOP_ID` afterward too if that change touched a
harness ARN.

### Backend wiring

`backend/config.py` reads harness ARNs, the Cognito pool/client ID, table names, and the Legacy Portal OAuth
identity/provider names from environment variables, falling back to a fixed set of `dev01` values that only exist
so the module imports cleanly — **they are not a valid target for anyone else to run against.** Run
`make wire-backend-env WORKSHOP_ID=$WORKSHOP_ID` yourself once you've built the harnesses and the OAuth resources
per WALKTHROUGH.md — it writes a real `backend/.env` by discovering your harness ARNs (via `agentcore status`) and
assuming your OAuth workload identity/credential provider are named `crexi<WORKSHOP_ID>legacyoauth`, exactly as
the walkthrough has you name them.

### Legacy Portal OAuth

Checkpoint 4's broker agent authorizes access to the legacy deal desk through a real per-user OAuth flow via
AgentCore Identity's Token Vault, not a stored password. On this branch, you create the two AgentCore Identity
resources this needs — a workload identity and an OAuth2 credential provider pointing at the `LegacyOAuthAppClient`
Cognito app client from `identity_stack.py` — by hand, via WALKTHROUGH.md's Phase 3. That hands-on AgentCore
Identity work is a deliberate teaching moment, not an oversight.

The first time you actually chat as marcus and ask about a listing's rent roll, `get_legacy_credentials` will
return an authorization URL instead of a token — open it in your own browser (not the one AgentCore Browser
drives), sign in, and grant consent. That's a one-time step per broker; every later request reuses the cached
token with no repeat consent. See `backend/confirmation.py`'s module docs for the full flow, and note the
deliberate simplification called out there and in Known Limitations below.

## Known limitations

- **Underwriting compliance is a heuristic safety net, not a hard guarantee.** The backend detects an assistant
  reply that states cap rate/DSCR/cash-on-cash figures without having called the Code Interpreter tool that turn,
  and forces one corrective retry. The underlying model can still occasionally bypass Code Interpreter on both the
  original attempt and the retry — there is no deterministic `toolChoice`-style lever exposed anywhere in
  AgentCore Harness's own configuration surface to force a specific tool call (confirmed against the CLI's schema
  and AWS's own API docs). Treat a bypass as a known, open model-behavior issue, not a deployment bug.
- **This backend keeps paused-run state (an in-flight price-change confirmation) in memory**, keyed by run ID —
  fine for a single-process workshop backend, but a restart mid-confirmation strands that run. A production version
  would persist this (e.g. in DynamoDB).
- **The Legacy Portal OAuth access token travels as a `?access_token=` URL query parameter**, not a cookie or
  header. This is a deliberate workshop simplification, not an oversight: the Harness's built-in Browser tool only
  exposes human-like actions (navigate/click/type), so there is no way for the model to set a cookie or header
  directly, and navigating with the token in the URL is the only path available. In production, mint a short-lived,
  single-use exchange code instead (the same pattern `confirm_listing_change` already uses for price-change
  approvals) so the real bearer token never lands in an access log or an AgentCore Browser session recording.

## Troubleshooting

| Symptom | Likely cause |
| --- | --- |
| `aws sts get-caller-identity failed` | Credentials expired (common with temporary/session credentials) — get fresh ones and re-run. |
| `effective region is 'X', not us-west-2` | `AWS_REGION`/`AWS_DEFAULT_REGION` in your shell is overriding an otherwise-correctly-configured AWS CLI profile. |
| `CDK not bootstrapped` | Run `cdk bootstrap` once for your account/region. |
| `agentcore --version` prints nothing useful | An old `pip install bedrock-agentcore-starter-toolkit` is shadowing the real npm `agentcore` CLI on `PATH`. |
| `Invalid harness configuration: ... config file not found` | `agentcore.json`'s harness `path` doesn't match a real directory — check the harness's `name`/`path` against WALKTHROUGH.md's naming convention before the next `agentcore deploy`. |
| Broker's legacy-desk `/sso` login fails ("Invalid or expired access token") | The legacy desk URL pasted into the broker's system prompt points at a different participant's deployment (copied from an example instead of your own `LegacyStack`'s `LegacyDeskUrl` output), whose OAuth pool doesn't recognize your token. |
| `make dev` says `backend/.env not found` | Run `make wire-backend-env WORKSHOP_ID=$WORKSHOP_ID` once you've built the harnesses and OAuth resources per WALKTHROUGH.md — nothing writes this file automatically on this branch. |
| `pip install` failures during `make bootstrap` | First-run setup: `make bootstrap` provisions `infra/.venv`, `backend/.venv`, and `frontend/node_modules` on its own the first time it runs (a few extra minutes) — no manual install needed. If it still fails, you likely have no network access to PyPI/npm (corporate proxy/firewall); fix that and re-run `make bootstrap`, which is safe to retry. |
| `sh: tsc: command not found` during Phase 0/`agentcore deploy` | `agentcore/cdk`'s own `npm install` (WALKTHROUGH.md Phase 0) didn't complete — re-run `cd agentcore/cdk && npm install`. |
| `uvicorn`/Vite fails with `Address already in use` on `:8000` or `:5173` | A previous `make dev` (yours or a leftover process) is still holding the port — find it with `lsof -i :8000` and stop that specific process, then re-run `make dev`. Don't `pkill` by name; that can kill an unrelated process reusing the same command name. |
| A harness call fails with `Unknown tool: <name>` after you added a custom tool | `harness.json`'s `allowedTools` needs an `@`-prefixed reference for any tool that isn't one of AWS's fixed built-ins (e.g. `@my-custom-tool`, matching how Gateway tools are already listed as `@market-data/*`) — a bare name in `allowedTools` only matches AWS's built-in tool identifiers and silently rejects everything else before it dispatches. |

## Repository layout

```
crexiWorkshopV2/
├── Makefile                    # preflight, bootstrap (CDK only), deploy, seed, dev, destroy
├── WALKTHROUGH.md               # Everything AgentCore-native: build it here, by hand
├── (no agentcore/ or app/ yet -- WALKTHROUGH.md's Phase 0 creates agentcore/, later phases create app/)
├── infra/                      # CDK: Data, Identity, Legacy, Tools, Observability stacks
├── services/
│   ├── mcp_market_data/        # Lambda: search_listings, get_listing, get_market_comps, documents
│   ├── mcp_listing_ops/        # Lambda: update_listing_price (approval-token gated)
│   ├── legacy_deal_desk/       # The no-API legacy app the Browser tool logs into
│   └── seed/                   # Custom-resource handlers: seed data, seed legacy records, seed Cognito users
├── backend/                    # FastAPI: Cognito auth, /agui SSE endpoint, cost tracking
├── frontend/                   # React + Vite, CREXi-themed
└── scripts/
    ├── preflight.sh
    ├── vendor-deps.sh
    ├── ensure-aws-target.sh / remove-aws-target.sh
    └── wire-backend-env.sh      # Assumes you named things per WALKTHROUGH.md's convention
```

After WALKTHROUGH.md's Phase 0, you'll also have `agentcore/` (your project config + its own generated CDK
tooling) and, from Phases 1-2, `app/investorAgent_<id>/` and `app/brokerAgent_<id>/` (your two harnesses' configs
and system prompts).

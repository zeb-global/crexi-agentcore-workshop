# CREXi AgentCore Workshop

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
make wire-backend-env WORKSHOP_ID=$WORKSHOP_ID
make dev
```

`make bootstrap` takes a few minutes — on first run it also provisions `infra/.venv`, `backend/.venv`,
`agentcore/cdk/node_modules`, and `frontend/node_modules` before deploying 5 CDK stacks (data, identity, legacy
desk, tool Lambdas, observability) and then the AgentCore harnesses and Gateways in two passes (see below for
why). `make dev` starts the FastAPI backend on `:8000` and the Vite frontend on `:5173`; open
**http://localhost:5173**.

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
  <two of the properties it lists>, minimum cap rate 6.5%." Watch the tool-activity panel — underwriting should go
  through a real Code Interpreter execution, not the model just typing numbers.
- **As marcus (broker):** "What listings do I have?", then "Change the asking price on <one of them> to
  <a new number>." — this pauses for your explicit confirmation before writing anything. Also try: "Check the rent
  roll for <a listing> on the legacy deal desk" — this drives a real browser session through a separate login-gated
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
   the harness's own IAM Role name) is a literal string taken straight from `agentcore.json`, **not** namespaced by
   the target. Two participants both deploying a harness literally named `investorAgent` collide on the same IAM
   Role even in separate stacks. So [`scripts/render_agentcore_config.py`](scripts/render_agentcore_config.py)
   suffixes every one of those names with your `WORKSHOP_ID` before every deploy.

2. A harness's Gateway reference (`tools[].config.agentCoreGateway.gatewayArn`) is a **resolved literal ARN**, not
   an in-stack CDK reference — and AWS only assigns that ARN once the Gateway actually exists. So `make bootstrap`
   deploys in two passes: your uniquely-named Gateways first, then reads their real ARNs back and deploys your
   uniquely-named harnesses referencing them.

3. `agentcore validate` derives a harness's config directory from its registry `name` as `app/<name>/harness.json`
   — not the schema's own separate `path` field. So a per-participant harness needs its own directory; the render
   script generates `app/investorAgent_<id>/` and `app/brokerAgent_<id>/` by copying the canonical
   `app/investorAgent/` and `app/brokerAgent/` sources and patching the copy. **Edit the canonical
   `app/investorAgent/system-prompt.md` and `harness.json`** (or `app/brokerAgent/...`) to change agent behavior for
   everyone — the generated `_<id>` directories are gitignored, regenerated on every deploy, and should never be
   hand-edited.

4. `app/brokerAgent/system-prompt.md` names the legacy deal desk's Lambda Function URL as literal text (for the
   model to navigate the Browser tool to). That URL is unique per participant too (`LegacyStack`'s
   `LegacyDeskUrl` output) — the render script patches it into the generated `system-prompt.md` the same way.

If you ever see a broker harness fail to log into the legacy desk, or an investor harness returning another
participant's listings, one of these four is the first thing to check — it almost certainly means `agentcore.json`
was last rendered/deployed for a *different* `WORKSHOP_ID` than the one you're currently testing.

### `make deploy` vs `make bootstrap`

`make bootstrap` is the full first-time path (CDK + two-phase AgentCore deploy). If you only change a
`system-prompt.md` or `harness.json` afterward, you don't need a full CDK re-deploy — `make deploy
WORKSHOP_ID=$WORKSHOP_ID` re-renders and redeploys just the harness layer, reusing your already-deployed Gateways.

### Backend wiring

`backend/config.py` reads harness ARNs, the Cognito pool/client ID, and table names from environment variables,
falling back to a fixed set of `dev01` values that only exist so the module imports cleanly — **they are not a
valid target for anyone else to run against.** `make wire-backend-env WORKSHOP_ID=$WORKSHOP_ID` (backed by
[`scripts/wire-backend-env.sh`](scripts/wire-backend-env.sh)) writes a real `backend/.env` for your own deployment;
`make dev` refuses to start without one.

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

## Troubleshooting

| Symptom | Likely cause |
| --- | --- |
| `aws sts get-caller-identity failed` | Credentials expired (common with temporary/session credentials) — get fresh ones and re-run. |
| `effective region is 'X', not us-west-2` | `AWS_REGION`/`AWS_DEFAULT_REGION` in your shell is overriding an otherwise-correctly-configured AWS CLI profile. |
| `CDK not bootstrapped` | Run `cdk bootstrap` once for your account/region. |
| `agentcore --version` prints nothing useful | An old `pip install bedrock-agentcore-starter-toolkit` is shadowing the real npm `agentcore` CLI on `PATH`. |
| `Invalid harness configuration: ... config file not found` | `agentcore.json`'s harness `path` doesn't match a real directory — almost always means `agentcore.json` needs re-rendering for your `WORKSHOP_ID` (`python3 scripts/render_agentcore_config.py $WORKSHOP_ID harnesses`) before the next `agentcore deploy`. |
| Broker's legacy-desk login fails with "Invalid username or password" | `agentcore.json`/the generated `system-prompt.md` was last rendered for a different `WORKSHOP_ID` — re-render and redeploy for yours. |
| `make dev` says `backend/.env not found` | Run `make wire-backend-env WORKSHOP_ID=$WORKSHOP_ID` first. |
| `sh: tsc: command not found` / `pip install` failures during `make bootstrap` | First-run setup: `make bootstrap` provisions `infra/.venv`, `backend/.venv`, `agentcore/cdk/node_modules`, and `frontend/node_modules` on its own the first time it runs (a few extra minutes) — no manual install needed. If it still fails, you likely have no network access to PyPI/npm (corporate proxy/firewall); fix that and re-run `make bootstrap`, which is safe to retry. |
| `uvicorn`/Vite fails with `Address already in use` on `:8000` or `:5173` | A previous `make dev` (yours or a leftover process) is still holding the port — find it with `lsof -i :8000` and stop that specific process, then re-run `make dev`. Don't `pkill` by name; that can kill an unrelated process reusing the same command name. |
| A harness call fails with `Unknown tool: <name>` after you added a custom tool | `harness.json`'s `allowedTools` needs an `@`-prefixed reference for any tool that isn't one of AWS's fixed built-ins (e.g. `@my-custom-tool`, matching how Gateway tools are already listed as `@market-data/*`) — a bare name in `allowedTools` only matches AWS's built-in tool identifiers and silently rejects everything else before it dispatches. |

## Repository layout

```
crexiWorkshopV2/
├── Makefile                    # preflight, bootstrap, deploy, seed, dev, destroy
├── agentcore/
│   ├── agentcore.json          # Gateways, harness registry (rendered per-WORKSHOP_ID before each deploy)
│   ├── aws-targets.json        # One entry per participant (added by scripts/ensure-aws-target.sh)
│   └── .cli/deployed-state.json
├── app/
│   ├── investorAgent/          # Canonical harness.json + system-prompt.md -- EDIT THESE
│   └── brokerAgent/            # Canonical harness.json + system-prompt.md -- EDIT THESE
│   # app/investorAgent_<id>/, app/brokerAgent_<id>/ are generated per-participant, gitignored
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
    ├── render_agentcore_config.py   # The per-participant isolation fix -- see above
    └── wire-backend-env.sh
```

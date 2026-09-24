# Handoff — CREXi AgentCore Workshop (legacy-oauth-workshop-v2)

Written 2026-09-23 for continuity if this session runs out of credits mid-task.
Read this fully before touching anything — it has the exact state, the exact
gotchas already hit, and what's still open.

## Repo / branch state

- Repo: `~/Documents/Crexi LA/build/crexiWorkshopV2`
- Current branch: `legacy-oauth-workshop-v2`, based off `substrate/frontend-redesign`
- This branch = the **reference branch**: one command (`make bootstrap
  WORKSHOP_ID=<id> WORKSHOP_SECRET=<secret>`) deploys everything end-to-end —
  CDK stacks, AgentCore gateways/harnesses, and the Legacy Portal OAuth
  workload identity + credential provider. `make dev` then just works.
- Uncommitted at time of writing:
  - `app/brokerAgent/system-prompt.md` — deterministic OAuth-retry fix (see
    below). **Commit this.**
  - `frontend/src/App.jsx` — chat markdown links now open in a new tab
    (`target="_blank"`) so clicking the OAuth authorizationUrl doesn't
    navigate the app away from itself. **Commit this.**
  - `agentcore/.cli/deployed-state.json`, `agentcore/agentcore.json`,
    `agentcore/aws-targets.json`, `agentcore/cdk/package-lock.json` — CLI
    tooling's own bookkeeping from live deploys this session. Check `git
    diff` before committing; these may just be noise from the AgentCore CLI
    touching its own state files, or they may carry real config changes
    (e.g. harness version bumps) that should be committed.
  - `services/legacy_deal_desk/certifi/` untracked — vendored dependency,
    should already be gitignored alongside `jose`/`ecdsa`/`rsa`/`pyasn1`; if
    `git status` still shows it, check `.gitignore` covers it.

## AWS environment

- Sandbox account via AWS profile `crexi-sandbox` (also `crexi-test` exists,
  unused). Credentials are DCE temporary tokens that **expire and need
  manual refresh by the user** — if any AWS CLI call fails with
  `ExpiredTokenException` or SSO token errors, stop and ask the user to
  refresh, then verify with `aws sts get-caller-identity --profile
  crexi-sandbox` before continuing.
- Region: `us-west-2` always. Set `AWS_PROFILE=crexi-sandbox AWS_REGION=us-west-2
  AWS_DEFAULT_REGION=us-west-2` for every shell command.
- Live test deployment in this account right now: `WORKSHOP_ID=oauthe2e01`
  (CloudFormation stacks `Crexioauthe2e01*`, DynamoDB tables
  `crexi-oauthe2e01-*`, Cognito pool `us-west-2_2WZQcX9vp`). This has been
  used for real end-to-end testing all session — safe to keep reusing it,
  or `make destroy WORKSHOP_ID=oauthe2e01` and re-bootstrap fresh if you
  want a clean slate for final validation.
- Demo users: `dana` (investors) / `marcus` (brokers). Their passwords are
  **deterministically derived** from `WORKSHOP_SECRET` (see
  `infra/cdk.out/asset.*/seed_users_handler.py`:
  `Wk-{sha256(f"{secret}:{username}")[:20]}!9`) — if you don't have the
  original `WORKSHOP_SECRET` used for a deploy, you cannot derive the
  password; just `aws cognito-idp admin-set-user-password --user-pool-id
  <pool> --username marcus --password '<NewPass1!>' --permanent` to reset it
  directly. Currently marcus's password on `oauthe2e01` is
  `Wk-TempDemo2026!9` (manually reset this session, not derived).
- `backend/.env` for `oauthe2e01` already written — see
  `scripts/wire-backend-env.sh` output. If it's missing/stale, rerun
  `make wire-backend-env WORKSHOP_ID=oauthe2e01`.

## What's fully built and verified this session

1. **Backend/frontend OAuth wiring** (Checkpoint 4, Legacy Portal OAuth) —
   real per-user 3-legged OAuth via AgentCore Identity's Token Vault,
   replacing the old stored-DynamoDB-password approach. Explicitly a
   workshop simplification (token passed as a URL query param to the
   Browser tool, documented in `services/legacy_deal_desk/app.py`'s module
   docstring and the README's Known Limitations).
   - `infra/stacks/identity_stack.py` — Cognito Hosted UI OAuth app client
     reused on the main user pool.
   - `infra/stacks/legacy_stack.py`, `infra/app.py` — wiring OAuth issuer/
     client id into the legacy Lambda.
   - `services/legacy_deal_desk/app.py` — `/sso?access_token=` route,
     verifies the token via JWKS (`python-jose`, bare install — no
     `[cryptography]` extra, to avoid compiled-extension platform
     mismatches between dev laptop and Lambda ARM64).
   - `backend/confirmation.py` — `resolve_legacy_credentials` /
     `complete_legacy_oauth`, real `GetWorkloadAccessTokenForUserId` →
     `GetResourceOauth2Token` → `CompleteResourceTokenAuth` flow.
   - `backend/main.py` — `/oauth/legacy-callback` route.
   - `scripts/setup-legacy-oauth.sh` — idempotent workload identity +
     `CognitoOauth2` credential provider setup. **Reference-branch only** —
     do not carry this script's automation into the workshop branch; on
     that branch participants run the equivalent AWS CLI commands by hand
     (not yet written, see Pending).
   - Verified live, twice, full round trip: consent → callback → Browser
     tool navigates to `/sso?access_token=...` → real rent-roll/concessions/
     deferred-maintenance data rendered in chat for Westerville Park.

2. **Real bug found and fixed**: the model was re-capitalizing
   `request_uri` → `request_URI` when relaying the authorization URL in
   chat (case-sensitive PAR identifier, breaks the link). Fixed via an
   explicit instruction in `app/brokerAgent/system-prompt.md`. Confirmed
   fixed via redeploy + live retest.

3. **Real bug found and fixed**: chat markdown links opened in the same
   browser tab, navigating the user's whole frontend away when they clicked
   the OAuth authorization link. Fixed in `frontend/src/App.jsx` (added
   `components={{a: ...target="_blank"}}` to the `ReactMarkdown` render).
   **Not yet live-verified in a browser** — do that first if continuing.

4. **Real bug found and fixed**: `scripts/vendor-deps.sh` only checked that
   `infra/.venv`/`backend/.venv` *directories* existed, not that `pip`
   inside them actually worked — a broken-but-present venv silently broke
   `make bootstrap`. Hardened to check `[ -x .../bin/pip ]` and recreate if
   not. User explicitly flagged this ("I want everything to work seemless
   with one command") — keep this bar for anything else you touch in the
   deploy path.

5. **Known, accepted, non-fixable quirk**: AgentCore's built-in Browser
   tool (used by the Harness) does not reliably persist its cookie/session
   across sequential `navigate` calls within one turn — sometimes the SSO
   redirect's session cookie survives to the next navigation, sometimes it
   doesn't, landing back on the legacy desk's login page. This is
   undocumented AWS behavior, not a config bug on our side (already
   double-checked: workload identity, credential provider, and Cognito app
   client configs were all confirmed correct via `aws
   bedrock-agentcore-control get-workload-identity` /
   `get-oauth2-credential-provider` / `aws cognito-idp
   describe-user-pool-client` while this was happening). **Just fixed**:
   `app/brokerAgent/system-prompt.md` now explicitly instructs the model to
   silently detect a login-page redirect and retry (fresh
   `get_legacy_credentials` → fresh `/sso` navigation) without narrating it
   as an error to the broker. **This fix has NOT yet been deployed or
   live-verified** — that's the very next step (see Pending #1).

6. **Reference branch's one-command deploy** — `make bootstrap
   WORKSHOP_ID=<id> WORKSHOP_SECRET=<secret>` now runs the full path: CDK
   deploy (all stacks) → gateway-only AgentCore deploy → render harnesses
   against real gateway ARNs → harness AgentCore deploy →
   `wire-backend-env.sh` (harness ARNs, Cognito, and the Legacy OAuth
   workload identity/credential provider, all in one shot). `make dev`
   needs nothing else run first. This satisfies the user's explicit
   requirement: "I need everything to work seamless with one command."

## Pending — in priority order

1. ~~Deploy + live-verify the system-prompt OAuth-retry fix.~~ **DONE.**
   Deployed (`make deploy WORKSHOP_ID=oauthe2e01`, broker harness now at
   v3). Live-verified via the real chat UI as marcus: asked for Westerville
   Park's legacy data, the model ran 4 "Browser session" tool-call steps
   (consistent with the retry firing internally) and returned clean data
   with zero error narration -- exact text was "I have credentials. Let me
   log in and pull up the Westerville Park data. Here is the current
   legacy deal desk data..." followed by the correct rent roll/concessions/
   deferred-maintenance table. No regression.

2. ~~Live-verify the frontend link-target fix with a FRESH authorization.~~
   **DONE.** Forced a fresh OAuth prompt by deleting + recreating
   `crexioauthe2e01legacyoauth` (see recipe below), which cleared marcus's
   cached token. Chat then rendered a genuine authorizationUrl link
   ("Authorize Legacy Deal Desk Access"). Confirmed via
   `document.querySelectorAll('a')` in the live page that the rendered
   anchor has `target="_blank" rel="noopener noreferrer"` -- the fix is
   live and correct.
   - Did NOT click through the rest of that particular authorization (no
     need -- the link-target attribute was the only thing being tested,
     and DOM inspection is definitive proof). If you want the full round
     trip re-verified end to end again after this, it's the same procedure
     already proven working earlier in this doc.
   - **Two more real things surfaced while forcing this fresh-auth test,
     both already noted under Gotchas below, but flagging here too since
     they directly affected this test run:** (a) a transient
     `ConnectionResetError` on one attempt corrupted that AgentCore
     session's conversation state (see "Inline function tool corruption"
     gotcha), requiring a full page reload / fresh thread to recover --
     not related to the OAuth work, a pre-existing structural risk; (b) AWS
     sandbox credentials expired mid-test again, requiring a user refresh
     + backend restart.

3. **Confirm Makefile consolidation is actually complete.** Re-read the
   current `Makefile` and `scripts/wire-backend-env.sh` top to bottom and
   check there's no leftover redundant step or script the user would
   consider "too many .sh files / make commands" (this was an earlier
   explicit complaint, already mostly addressed by commit "Consolidate the
   reference branch into one deploy command" — verify nothing regressed).

4. **Full end-to-end validation pass** — same rigor as everything already
   done this session, run once against the current code:
   - Fresh `WORKSHOP_ID` (or `make destroy` + re-bootstrap `oauthe2e01`) to
     prove the one-command bootstrap really works from zero, not just
     incrementally.
   - Both harnesses (investor + broker) respond correctly as their
     respective demo users.
   - Full OAuth Legacy Portal round trip via the real chat UI, including at
     least one retry-recovery case to prove item #1's fix actually works
     under the flaky-cookie condition (may need multiple attempts to catch
     it happening).
   - `make seed`, `make verify`, `make destroy` all still work.

5. **Build the workshop branch** (not started at all — this is the largest
   remaining piece of work):
   - New branch off this one (or off `substrate/frontend-redesign`
     directly — confirm with user which base).
   - `Makefile`'s `bootstrap` target on this branch stops after `cdk deploy
     --all` — no gateway/harness rendering, no `agentcore deploy`, no
     `wire-backend-env.sh` call. Everything AgentCore-native is manual.
   - `scripts/render_agentcore_config.py` and `scripts/setup-legacy-oauth.sh`
     are **reference-branch only** — either remove them from this branch or
     leave them but make clear in the walkthrough participants don't run
     them.
   - Write the full participant walkthrough doc covering:
     - Phase 0: baseline-only deploy (`make bootstrap`, CDK stacks only).
     - Phase 1: investor harness via the interactive `agentcore add
       harness` TUI.
     - Phase 2: broker harness via atomic one-shot `agentcore` CLI commands
       (already scoped earlier in this session as ~5 CLI steps for the
       OAuth credential-provider setup specifically — recover that exact
       command list from this session's history if not already written
       down anywhere, or re-derive it from `scripts/setup-legacy-oauth.sh`'s
       logic, converting each idempotent AWS/agentcore CLI call in that
       script into an explicit manual step).
     - Backend `.env` wiring: the 3 new OAuth-related values
       (`LEGACY_OAUTH_WORKLOAD_NAME`, `LEGACY_OAUTH_PROVIDER_NAME`,
       `LEGACY_OAUTH_RETURN_URL`) plus the existing harness ARNs/Cognito
       values — probably still via `make wire-backend-env`, but confirm
       that target doesn't call the reference-only OAuth setup script on
       this branch (it currently does — **this needs to change** on the
       workshop branch: split `wire-backend-env.sh` so it captures OAuth
       env values that the participant already created by hand, instead of
       creating them itself).
     - A "Known Limitations" style callout on the token-in-URL
       simplification, matching what's already in this branch's README.
   - `backend/confirmation.py`, `backend/main.py`, all frontend code, and
     the harness system prompts stay **pre-built** on the workshop branch
     too — only the AgentCore CLI resource-creation work is manual. This
     was an explicit, repeated user requirement.
   - Once built, this branch needs its own full live end-to-end validation
     pass (same rigor as #4), actually following the walkthrough as a
     participant would, not just assuming it's correct.

## How to force fresh OAuth authorization (no clean revoke API exists)

There is no `delete`/`revoke` call for a cached Token Vault entry --
confirmed by reading every `bedrock-agentcore-control` and
`bedrock-agentcore` CLI command this session; only get/complete operations
exist. The practical way to force `get_legacy_credentials` back down the
`authorizationRequired` path:
```bash
export AWS_PROFILE=crexi-sandbox AWS_REGION=us-west-2
aws bedrock-agentcore-control delete-oauth2-credential-provider --name crexioauthe2e01legacyoauth
bash scripts/setup-legacy-oauth.sh oauthe2e01 http://localhost:8000/oauth/legacy-callback
```
This deletes and recreates the credential provider (same name, same
config), which orphans/clears any cached token for marcus without
affecting the workload identity or Cognito app client. Not yet tried this
session -- do this first if you need to test the fresh-authorization path.

## Real UX gap found and fixed: chat didn't auto-resume after OAuth consent

User tested the real flow (their own browser, real click, real Cognito
login) and found that after granting consent in the new tab, the original
chat just sat there -- they had to come back and type something before the
agent would retry. The design always required this (system prompt says
"tell the broker... ask them to let you know"), but the user reasonably
expected auto-resume the instant authorization completed. Fixed this
session:
- `backend/confirmation.py` -- added `_completed_oauth_sessions` set and
  `is_oauth_session_complete()`, populated in `complete_legacy_oauth()`.
- `backend/main.py` -- new `GET /oauth/legacy-status?session_uri=` endpoint.
- `frontend/src/api.js` -- `checkLegacyOAuthStatus()`.
- `frontend/src/App.jsx` -- `extractPendingOAuthSessionUri()` pulls the
  opaque `request_uri` out of the assistant's rendered authorizationUrl;
  a `useEffect` polls `/oauth/legacy-status` every 2s (8-minute cap, under
  the PAR request's own ~10min server-side TTL) while one is outstanding,
  and on completion auto-sends a normal user turn ("I've completed the
  authorization -- please continue.") via a new shared `sendTurn()` (
  `handleSend` now just calls `sendTurn(input.trim())`). Poll is cleared on
  logout and on unmount.
- **Live-verified**: forced a fresh authorization link, then simulated the
  callback landing (`curl http://localhost:8000/oauth/legacy-callback?session_id=...`)
  instead of fighting the browser tool's flaky first-navigate/PAR-consumption
  issue below -- confirmed the chat auto-sent the continuation turn within
  ~2-4 seconds with zero manual input, and the agent picked the task back
  up to completion. This tests the polling/auto-continue mechanism
  specifically; the underlying real OAuth mechanics were already proven
  separately (see above).
- Did NOT change the system prompt's own "let me know" wording -- it's
  still accurate as a fallback (e.g. if the 8-minute poll window is
  exceeded, or JS is disabled), so left as-is deliberately.

## Real bug found (still just a hypothesis, not fully confirmed): my
browser tool's flaky first-navigate may be consuming single-use PAR URLs

While testing the above, hit the exact same "Invalid request" error from
much earlier in this session again, on a freshly generated,
never-before-used authorizationUrl. New theory, not yet proven: the browser
tool's well-known "first navigate to bedrock-agentcore.us-west-2.amazonaws.com
always fails, retry works" quirk might not be purely cosmetic -- if that
first failed attempt actually reaches AWS's server before failing
client-side, it could be consuming the single-use `request_uri` (PAR
semantics are explicitly single-use per AWS's own docs), so the "successful"
retry is really a second use of an already-burned token, hence "Invalid
request" every time. This would fully explain why: the user's own single
real click always works, but every attempt through my automated browser
tool's navigate-fails-then-retry pattern has failed. Not confirmed (would
need e.g. CloudTrail correlation of exact request timestamps), but a strong
working theory if this needs to be revisited later. Practical implication:
don't rely on this browser tool to test the live authorize-page hop end to
end -- test the pieces on either side of it instead (as done here: force
the link, then hit the callback directly to test resumption; the actual
Cognito consent hop is human-only anyway per the system's design).

## Real bug found: inline_function tool-call corruption on connection drop

Discovered while forcing the fresh-OAuth test above. If the harness invoke
stream breaks mid-response (`ConnectionResetError`/`ProtocolError`) while an
inline_function tool call (e.g. the browser tool, or `get_legacy_credentials`)
is pending, the harness's own conversation state for that `session_id` is
left with a dangling, unresolved `toolUseId`. Every subsequent message sent
on that SAME thread/session then hard-fails with:
```
botocore.exceptions.EventStreamError: An error occurred (runtimeClientError)
when calling the InvokeHarness operation: Inline function result is missing
toolUseId '<id>'.
```
There is no retry that fixes this **within the same session** -- the only
recovery found this session is starting a brand-new thread (a full frontend
page reload generates a fresh `threadId` in `frontend/src/App.jsx`, which
becomes a new `session_id` in `backend/main.py`, giving AgentCore a clean
conversation with no dangling tool call). This is a real reliability gap
worth flagging to AWS or handling defensively (e.g. the backend could catch
`EventStreamError` containing "missing toolUseId" and auto-start a fresh
session transparently instead of surfacing a raw network error to the
broker) -- **not yet fixed, just discovered and worked around manually.**
Consider this for a future backend hardening pass if there's time; it's not
blocking anything in the current workshop scope since it's rare (needs a
connection drop at exactly the wrong moment) but it's a real, reproducible
failure mode users would eventually hit in a real workshop with many
concurrent participants over live wifi.

## Gotchas to remember while working

- **Don't use `nohup ... &` under a backgrounded Bash `run_in_background:
  true` call** — the outer wrapper reports "completed" the instant the
  `nohup` line returns, while the real process (e.g. a `make deploy`) is
  still running. Get the real child PID via `ps aux | grep` and poll that
  PID directly if you need to block on completion.
- AWS credentials in this sandbox expire mid-session, sometimes more than
  once. Always verify with `aws sts get-caller-identity --profile
  crexi-sandbox` before trusting a failure is a real bug rather than an
  expired token.
- The backend FastAPI process caches whatever AWS credentials were active
  *when it started* — if you refresh AWS credentials while `make dev`'s
  backend is already running, DynamoDB/Cognito calls will keep failing with
  `ExpiredTokenException` until you **restart the backend process**, even
  though a fresh `aws sts get-caller-identity` succeeds. Hit this exact
  issue this session — kill and restart `uvicorn` after any credential
  refresh.
- Before concluding something is an AWS platform bug or limitation, check
  the AWS Console UI directly first, and take stubborn-seeming user pushback
  seriously — there's a standing note from a past mistake on this
  (`dont-conclude-platform-bug-too-fast` in this user's Claude memory).

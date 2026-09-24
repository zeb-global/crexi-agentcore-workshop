# Workshop Walkthrough

You've already run `make bootstrap WORKSHOP_ID=<id> WORKSHOP_SECRET=<secret>` — that deployed the CDK baseline
(5 stacks: Data, Identity, Legacy, Tools, Observability) and nothing else. Everything below is AgentCore-native
and you build it yourself, by hand. That's the actual point of this workshop: by the end, you'll have created a
Gateway, wired a Lambda target to it, built a Harness two different ways (an interactive TUI and atomic one-shot
CLI commands), and set up real per-user OAuth via AgentCore Identity's Token Vault.

Set these once and keep them exported in every terminal you use for the rest of this walkthrough:

```bash
export WORKSHOP_ID=<your workshop id>
export AWS_REGION=us-west-2
```

Every resource name you create below **must include your `WORKSHOP_ID`** — this AWS account is shared with every
other participant, and physical resource names (Gateway names, Harness names, the IAM Roles AgentCore creates for
them) are not automatically namespaced. `investorAgent` will collide with someone else's `investorAgent`;
`investorAgent_$WORKSHOP_ID` won't.

## What you already have

Confirm the baseline deployed before continuing:

```bash
aws cloudformation describe-stacks --stack-name "Crexi${WORKSHOP_ID}Tools" \
  --query "Stacks[0].Outputs" --output table
```

You should see `MarketDataFunctionArn` and `ListingOpsFunctionArn` — two Lambda functions you're about to wire up
as Gateway targets. Keep this command handy; you'll pull these ARNs again in a moment.

---

## Phase 1 — Investor Harness (interactive TUI)

The investor agent needs one Gateway (read-only market data) and a harness with Code Interpreter for underwriting
math. You'll build this one through `agentcore`'s interactive wizard, so you see every option it exposes.

### 1.1 — Create the read-only Gateway

```bash
agentcore add gateway
```

Answer the prompts:
- **Name**: `gw-readonly-${WORKSHOP_ID}`
- **Protocol type**: `MCP`
- **Authorizer type**: `AWS_IAM`
- **Enable semantic search**: yes
- **Exception level**: `NONE`

### 1.2 — Attach the market-data Lambda as a target

```bash
agentcore add gateway-target
```

- **Gateway**: `gw-readonly-${WORKSHOP_ID}` (the one you just created)
- **Name**: `market-data`
- **Type**: `lambda-function-arn`
- **Lambda ARN**: the `MarketDataFunctionArn` value from the command above
- **Tool schema file**: `agentcore/tool-schemas/market-data.json`
- **Outbound auth**: `none`

### 1.3 — Deploy the Gateway alone, first

A harness's Gateway reference is a resolved literal ARN, not a live CDK reference — AWS only assigns that ARN once
the Gateway actually exists. Deploy now, before creating the harness:

```bash
agentcore deploy --yes --target $WORKSHOP_ID
```

Then grab the ARN it just created:

```bash
agentcore status --target $WORKSHOP_ID --type gateway --json | python3 -c "
import json, sys
for r in json.load(sys.stdin)['resources']:
    print(r['name'], '->', r['identifier'])
"
```

Copy the ARN for `gw-readonly-${WORKSHOP_ID}` — you need it in the next step.

### 1.4 — Create the investor harness

```bash
agentcore add harness
```

Work through the wizard:
- **Name**: `investorAgent_${WORKSHOP_ID}`
- **Model provider**: `bedrock`
- **Model ID**: `us.anthropic.claude-sonnet-4-6`
- **Tools**: select `agentcore_gateway`, then `agentcore_code_interpreter`
  - **Gateway ARN**: the ARN you copied in 1.3
  - **Gateway outbound auth**: `awsIam`
- **Memory mode**: `managed`
- **Memory strategies**: `SEMANTIC`, `SUMMARIZATION`, `USER_PREFERENCE`
- **Memory event expiry**: `30` days
- **Allowed tools**: `@market-data/*,@code-interpreter`
- **System prompt**: accept the placeholder for now — you'll overwrite it next

The wizard creates `app/investorAgent_${WORKSHOP_ID}/harness.json` with a placeholder system prompt. Replace it
with the real one:

```bash
cp app/investorAgent/system-prompt.md app/investorAgent_${WORKSHOP_ID}/system-prompt.md
```

Sanity-check the result against the canonical shape (yours should match this, just with your own names/ARNs):

```bash
cat app/investorAgent/harness.json
```

### 1.5 — Deploy and verify

```bash
agentcore validate
agentcore deploy --yes --target $WORKSHOP_ID
agentcore invoke --target $WORKSHOP_ID --harness investorAgent_${WORKSHOP_ID} \
  --text "What multi-family listings are available in Columbus?"
```

You should get back real listings, with a `search_listings` tool call visible in the trace — not a hallucinated
answer.

---

## Phase 2 — Broker Harness (atomic CLI)

Same idea, but built entirely from one-shot flag commands instead of the interactive wizard — and this harness
needs more: a second Gateway (write operations), the Browser tool, and two custom `inline_function` tools that
the CLI has no flags for (you'll splice those into `harness.json` by hand — that's expected, not a workaround).

### 2.1 — Gateway + target, atomically

```bash
agentcore add gateway --name gw-ops-${WORKSHOP_ID} --protocol-type MCP \
  --authorizer-type AWS_IAM --exception-level NONE

agentcore deploy --yes --target $WORKSHOP_ID

LISTING_OPS_ARN=$(aws cloudformation describe-stacks --stack-name "Crexi${WORKSHOP_ID}Tools" \
  --query "Stacks[0].Outputs[?OutputKey=='ListingOpsFunctionArn'].OutputValue" --output text)

agentcore add gateway-target --gateway gw-ops-${WORKSHOP_ID} --name listing-ops \
  --type lambda-function-arn --lambda-arn "$LISTING_OPS_ARN" \
  --tool-schema-file agentcore/tool-schemas/listing-ops.json --outbound-auth none

agentcore deploy --yes --target $WORKSHOP_ID
```

Fetch both Gateway ARNs (readonly from Phase 1, ops from just now) the same way as step 1.3.

### 2.2 — The harness itself, atomically

```bash
agentcore add harness --name brokerAgent_${WORKSHOP_ID} \
  --model-provider bedrock --model-id us.anthropic.claude-sonnet-4-6 \
  --tools agentcore_gateway,agentcore_browser \
  --gateway-arn "<gw-ops ARN from 2.1>" --gateway-outbound-auth awsIam \
  --memory-mode managed --memory-strategies SEMANTIC,SUMMARIZATION,USER_PREFERENCE \
  --memory-event-expiry-days 30 \
  --allowed-tools "*"
```

This gives you one Gateway tool (`listing-ops`) and the Browser tool. You still need: the second Gateway
(`market-data`, read-only) and the two `inline_function` tools. Open
`app/brokerAgent_${WORKSHOP_ID}/harness.json` and add these two entries to the `tools` array (alongside what the
CLI already generated):

```json
{
  "type": "agentcore_gateway",
  "name": "market-data",
  "config": {
    "agentCoreGateway": {
      "gatewayArn": "<gw-readonly ARN from Phase 1>",
      "outboundAuth": { "awsIam": {} }
    }
  }
},
{
  "type": "inline_function",
  "name": "confirm_listing_change",
  "config": {
    "inlineFunction": {
      "description": "Ask the signed-in broker to confirm an exact listing price change before it is committed. Call this BEFORE update_listing_price, once you have the old and new price.",
      "inputSchema": {
        "type": "object",
        "properties": {
          "listingId": { "type": "string" },
          "oldPrice": { "type": "number" },
          "newPrice": { "type": "number" }
        },
        "required": ["listingId", "oldPrice", "newPrice"]
      }
    }
  }
},
{
  "type": "inline_function",
  "name": "get_legacy_credentials",
  "config": {
    "inlineFunction": {
      "description": "Get the login credentials for the signed-in broker's account on the legacy deal desk (a separate, no-API system reachable only through the browser tool). Call this once, before navigating there with the browser tool.",
      "inputSchema": { "type": "object", "properties": {} }
    }
  }
}
```

`inline_function` tools pause the harness and hand control back to whoever calls `InvokeHarness` (the backend) to
actually resolve them — that's why these two exist as backend Python functions
(`backend/confirmation.py`'s `resolve_legacy_credentials`/`mint_price_change_approval`), not Lambda-backed Gateway
targets. This is structural to AgentCore, not a design choice available to skip.

Copy over the real system prompt (do this now, before deploying):

```bash
cp app/brokerAgent/system-prompt.md app/brokerAgent_${WORKSHOP_ID}/system-prompt.md
```

Get your legacy desk URL and patch it into your copy:

```bash
aws cloudformation describe-stacks --stack-name "Crexi${WORKSHOP_ID}Legacy" \
  --query "Stacks[0].Outputs[?OutputKey=='LegacyDeskUrl'].OutputValue" --output text
```

Open `app/brokerAgent_${WORKSHOP_ID}/system-prompt.md` and replace the placeholder legacy-desk URL near the top
with your own.

### 2.3 — Deploy and verify

```bash
agentcore validate
agentcore deploy --yes --target $WORKSHOP_ID
agentcore invoke --target $WORKSHOP_ID --harness brokerAgent_${WORKSHOP_ID} \
  --text "What listings do I have?"
```

You won't be able to fully verify the legacy-desk lookup yet — that needs Phase 3's OAuth setup first. Confirming
`search_listings`/`get_listing` work here is enough for now.

---

## Phase 3 — Legacy Portal OAuth (Checkpoint 4)

The broker's `get_legacy_credentials` tool needs two AgentCore Identity resources: a **workload identity** and an
**OAuth2 credential provider** pointing at the Cognito app client `identity_stack.py` already created for exactly
this purpose. Five steps, all `aws` CLI — no `agentcore` CLI involved here, since these are Identity-service
resources, not project (`agentcore.json`) resources.

### 3.1 — Pull the values you need from the Identity stack

```bash
IDENTITY_STACK="Crexi${WORKSHOP_ID}Identity"
out() { aws cloudformation describe-stacks --stack-name "$IDENTITY_STACK" \
  --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text; }

USER_POOL_ID=$(out UserPoolId)
CLIENT_ID=$(out LegacyOAuthClientId)
ISSUER=$(out LegacyOAuthIssuer)
AUTH_ENDPOINT=$(out LegacyOAuthAuthorizationEndpoint)
TOKEN_ENDPOINT=$(out LegacyOAuthTokenEndpoint)
CLIENT_SECRET=$(aws cognito-idp describe-user-pool-client --user-pool-id "$USER_POOL_ID" \
  --client-id "$CLIENT_ID" --query 'UserPoolClient.ClientSecret' --output text)
```

### 3.2 — Create the workload identity

```bash
WORKLOAD_NAME="crexi${WORKSHOP_ID}legacyoauth"
RETURN_URL="http://localhost:8000/oauth/legacy-callback"

aws bedrock-agentcore-control create-workload-identity --name "$WORKLOAD_NAME"
aws bedrock-agentcore-control update-workload-identity --name "$WORKLOAD_NAME" \
  --allowed-resource-oauth2-return-urls "$RETURN_URL"
```

### 3.3 — Create the OAuth2 credential provider

```bash
PROVIDER_NAME="crexi${WORKSHOP_ID}legacyoauth"   # same name as the workload identity, by convention

PROVIDER_CONFIG=$(python3 -c "
import json
print(json.dumps({'includedOauth2ProviderConfig': {
    'clientId': '$CLIENT_ID', 'clientSecret': '$CLIENT_SECRET',
    'issuer': '$ISSUER', 'authorizationEndpoint': '$AUTH_ENDPOINT',
    'tokenEndpoint': '$TOKEN_ENDPOINT',
}}))
")

aws bedrock-agentcore-control create-oauth2-credential-provider --name "$PROVIDER_NAME" \
  --credential-provider-vendor "CognitoOauth2" --oauth2-provider-config-input "$PROVIDER_CONFIG"
```

The response includes a `callbackUrl` — copy it, you need it in the next step.

### 3.4 — Wire the callback URL back into Cognito

`update-user-pool-client` replaces the **whole** OAuth config, not just the callback list — so re-specify every
setting, or this silently clobbers the client's flows/scopes:

```bash
aws cognito-idp update-user-pool-client \
  --user-pool-id "$USER_POOL_ID" --client-id "$CLIENT_ID" \
  --allowed-o-auth-flows "code" --allowed-o-auth-scopes "openid" "email" \
  --allowed-o-auth-flows-user-pool-client --supported-identity-providers "COGNITO" \
  --callback-urls "https://example.com/callback" "<the callbackUrl from 3.3>"
```

### 3.5 — Sanity-check

```bash
aws bedrock-agentcore-control get-workload-identity --name "$WORKLOAD_NAME"
aws bedrock-agentcore-control get-oauth2-credential-provider --name "$PROVIDER_NAME"
```

Both should show up cleanly, the credential provider with `"status": "READY"`.

---

## Phase 4 — Backend Wiring

```bash
make wire-backend-env WORKSHOP_ID=$WORKSHOP_ID
```

This discovers your two harness ARNs (via `agentcore status`), your Cognito pool/client, and assumes your Phase 3
resources are named `crexi${WORKSHOP_ID}legacyoauth` — exactly as steps 3.2/3.3 had you name them. Open
`backend/.env` and confirm all seven values are non-empty before continuing.

```bash
make dev
```

Open **http://localhost:5173**. Log in as `dana` (investor) or `marcus` (broker) — passwords are derived from your
`WORKSHOP_SECRET`, same formula as the main README's [Logging in](README.md#logging-in) section.

---

## Verification Checklist

- [ ] **Investor**: "What multi-family listings are available in Columbus?" returns real listings.
- [ ] **Investor**: "Run underwriting on `<two properties>`, minimum cap rate 6.5%." goes through a visible Code
      Interpreter tool call, not just the model typing numbers.
- [ ] **Broker**: "What listings do I have?" returns only `marcus`'s own listings.
- [ ] **Broker**: "Change the asking price on `<a listing>` to `<a number>`." pauses for your explicit confirmation
      before writing anything.
- [ ] **Broker**: "Check the rent roll for `<a listing>` on the legacy deal desk." — first time, returns an
      authorization link; open it, sign in, grant consent, and the chat resumes on its own within a few seconds
      and returns real rent-roll/concessions/deferred-maintenance data.

---

## Known Limitations

Same callout as the reference branch, worth repeating since you're the one who wired this by hand this time: **the
Legacy Portal OAuth access token travels as a `?access_token=` URL query parameter**, not a cookie or header. This
is a deliberate workshop simplification — the Harness's built-in Browser tool only exposes human-like actions
(navigate/click/type), so there's no way for the model to set a cookie or header directly. In production, mint a
short-lived, single-use exchange code instead (the same pattern `confirm_listing_change` already uses for
price-change approvals), so the real bearer token never lands in an access log or a Browser session recording.

---

## Troubleshooting

| Symptom | Likely cause |
| --- | --- |
| `Invalid harness configuration: ... config file not found` | Your harness's `name` in `agentcore.json` doesn't match its directory under `app/`. `agentcore add harness` should keep these in sync automatically — if you hand-edited `harness.json`'s `name` afterward, the directory won't have been renamed to match. |
| `update-oauth2-credential-provider`/`create-oauth2-credential-provider` complains about a missing vendor | `--credential-provider-vendor "CognitoOauth2"` is required and easy to drop when copy-pasting partial commands — check it's present. |
| Broker's legacy-desk step returns "Invalid or expired access token" | Your `LegacyDeskUrl` (patched into `system-prompt.md` in step 2.2) or your `LEGACY_OAUTH_*` names in `backend/.env` don't match what you actually created in Phase 3 — re-check both against the exact `WORKSHOP_ID`-suffixed names used above. |
| `infra/.venv`/`backend/.venv` exists but `pip install` fails inside it | The venv is present but broken (e.g. left over from a system Python upgrade). `rm -rf infra/.venv backend/.venv` and re-run `make bootstrap`/`make wire-backend-env` — `scripts/vendor-deps.sh` recreates them cleanly. |
| A harness call fails with `Unknown tool: <name>` after adding a custom tool | `allowedTools` needs an `@`-prefixed reference for anything that isn't one of AWS's fixed built-ins (e.g. `@market-data/*`, `@code-interpreter`) — a bare name only matches built-in tool identifiers. |
| `make dev` says `backend/.env not found` | Run `make wire-backend-env WORKSHOP_ID=$WORKSHOP_ID` — Phase 4, above. Nothing writes this file automatically on this branch. |

If you get well and truly stuck, the `reference` branch has a fully working, automated version of everything
above — useful as an answer key, not as something to copy wholesale (the point is building it yourself).

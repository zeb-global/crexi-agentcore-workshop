# Workshop Walkthrough

You've already run `make bootstrap WORKSHOP_ID=<id> WORKSHOP_SECRET=<secret>` — that deployed the CDK baseline
(5 stacks: Data, Identity, Legacy, Tools, Observability) and nothing else. There is no `agentcore/` or `app/`
directory in this repo yet — you create both from scratch below. Every command in this walkthrough is given as
explicit, non-interactive CLI flags (not the interactive wizard) so it's exactly reproducible from this document.

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

## Phase 0 — Bootstrap the AgentCore project

`agentcore/agentcore.json` (the project config every `agentcore add`/`agentcore deploy` command reads and writes)
doesn't exist yet. `agentcore create` is what generates it — but it always creates a **new project subfolder**, it
doesn't initialize in place. So: run it in a scratch directory, then move just the pieces you need into this repo.

```bash
mkdir -p /tmp/agentcore-init && cd /tmp/agentcore-init
agentcore create --project-name crexiWorkshopV2 --no-agent --skip-git --skip-install --output-dir .
```

`--no-agent` matters — without it, this also scaffolds an unrelated runtime-agent code skeleton
(`app/crexiWorkshopV2/main.py`) you don't want. This creates `/tmp/agentcore-init/crexiWorkshopV2/agentcore/` —
config JSON plus a generated CDK project (`agentcore deploy`'s own deployment mechanism, not something you
hand-write). Move just that into your repo:

```bash
cd - # back to your repo root
cp -r /tmp/agentcore-init/crexiWorkshopV2/agentcore ./agentcore
rm -rf /tmp/agentcore-init
```

Install its CDK project's own dependencies (skipped above with `--skip-install`):

```bash
cd agentcore/cdk && npm install && cd -
```

Confirm you now have a real, empty project:

```bash
cat agentcore/agentcore.json
```

You should see `"agentCoreGateways": []` and `"harnesses": []` — an empty project with your project name, ready
for you to add resources to. Everything from here is `agentcore add ...` commands building this file up.

---

## Phase 1 — Investor Harness

The investor agent needs one Gateway (read-only market data), a tool schema describing that Lambda's tools, and a
harness with Code Interpreter for underwriting math.

### 1.1 — Write the market-data tool schema

`agentcore add gateway-target` needs a schema file describing the Lambda's tools (name, description, input shape)
— this describes the **already-built** `mcp-market-data` Lambda's contract (see
`services/mcp_market_data/handler.py` if you want to see where these tool names come from), not something you
derive from scratch:

```bash
mkdir -p agentcore/tool-schemas
cat > agentcore/tool-schemas/market-data.json <<'EOF'
[
  {
    "name": "search_listings",
    "description": "Search Columbus multi-family listings by market, asset type, unit range, price ceiling, and value-add flag.",
    "inputSchema": {
      "type": "object",
      "properties": {
        "market": {"type": "string", "description": "e.g. columbus-oh"},
        "assetType": {"type": "string", "description": "e.g. multifamily"},
        "unitsMin": {"type": "integer"},
        "unitsMax": {"type": "integer"},
        "priceMax": {"type": "number"},
        "valueAdd": {"type": "boolean"}
      }
    }
  },
  {
    "name": "get_listing",
    "description": "Get a single listing by its listingId.",
    "inputSchema": {
      "type": "object",
      "properties": {"listingId": {"type": "string"}},
      "required": ["listingId"]
    }
  },
  {
    "name": "get_market_comps",
    "description": "Recent Columbus multi-family comparable sales and their cap rates.",
    "inputSchema": {"type": "object", "properties": {}}
  },
  {
    "name": "list_property_documents",
    "description": "List the PDF documents available for a listing (e.g. T-12 operating statement, offering memorandum).",
    "inputSchema": {
      "type": "object",
      "properties": {"listingId": {"type": "string"}},
      "required": ["listingId"]
    }
  },
  {
    "name": "get_document_text",
    "description": "Extract text from a listing's PDF document. Net operating income (NOI) exists ONLY here, inside the T-12 operating statement -- it is not in any structured field.",
    "inputSchema": {
      "type": "object",
      "properties": {
        "listingId": {"type": "string"},
        "documentName": {"type": "string", "description": "e.g. T12_2025.pdf or OM.pdf"}
      },
      "required": ["listingId", "documentName"]
    }
  }
]
EOF
```

### 1.2 — Create the read-only Gateway

```bash
agentcore add gateway --name gw-readonly-${WORKSHOP_ID} --protocol-type MCP \
  --authorizer-type AWS_IAM --exception-level NONE
```

### 1.3 — Attach the market-data Lambda as a target

```bash
MARKET_DATA_ARN=$(aws cloudformation describe-stacks --stack-name "Crexi${WORKSHOP_ID}Tools" \
  --query "Stacks[0].Outputs[?OutputKey=='MarketDataFunctionArn'].OutputValue" --output text)

agentcore add gateway-target --gateway gw-readonly-${WORKSHOP_ID} --name market-data \
  --type lambda-function-arn --lambda-arn "$MARKET_DATA_ARN" \
  --tool-schema-file agentcore/tool-schemas/market-data.json
```

### 1.4 — Deploy the Gateway alone, first

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

### 1.5 — Create the investor harness

```bash
agentcore add harness --name investorAgent_${WORKSHOP_ID} \
  --model-provider bedrock --model-id us.anthropic.claude-sonnet-4-6 \
  --tools agentcore_gateway,agentcore_code_interpreter \
  --gateway-arn "<gw-readonly ARN from 1.4>" --gateway-outbound-auth awsIam \
  --memory-mode managed --memory-strategies SEMANTIC,SUMMARIZATION,USER_PREFERENCE \
  --memory-event-expiry-days 30 \
  --allowed-tools "@market-data/*,@code-interpreter"
```

This creates `app/investorAgent_${WORKSHOP_ID}/harness.json` with a placeholder system prompt. Replace it with the
real one:

```bash
cat > app/investorAgent_${WORKSHOP_ID}/system-prompt.md <<'EOF'
You are CREXi's investor-facing assistant for commercial real estate. You help
investors find and evaluate multi-family listings.

Grounding rules:
- Never state a property name, address, unit count, price, or any figure
  that did not come from a tool call this turn or from memory context
  clearly labeled as this user's prior stored criteria. If you are not sure
  a property exists, call search_listings or get_listing to check.
- Units and asking price come from search_listings / get_listing. Market
  cap rates and comparable sales come from get_market_comps. Net operating
  income (NOI) exists ONLY inside a listing's T-12 operating statement PDF
  -- retrieve it with get_document_text(listingId, "T12_2025.pdf"). It is
  not a field on the listing itself, and you must never estimate or recall
  it from memory.
- When a returning user has stored criteria (market, unit range, asking
  price ceiling, minimum cap rate, value-add preference), apply them without
  asking the user to repeat them.
- Be proactive: once the user's intent is clear (e.g. "what's new in
  Columbus"), immediately call search_listings with their stored or stated
  criteria, then pull documents and run the underwriting -- do not stop to
  ask permission to search. Never invent a result instead of calling a tool.
- Never state internal system data: listing IDs (e.g. "westerville-park"),
  database version numbers, raw tool-call statuses, timestamps, session
  IDs, or any other internal identifier. Refer to a property only by its
  name. If a listing's price or details recently changed, say so in plain
  language ("the asking price was recently updated") -- never cite a
  version number or record ID as evidence.
- Never narrate your own tool-calling mechanics, retries, or backend
  requirements to the user ("the backend requires...", "let me initialize
  a fresh session", "you're right, I apologize, running X now"). If a
  tool call is rejected and you need to retry, just retry silently and
  give the user only the final, correct answer -- never explain what went
  wrong internally or how you fixed it.

Underwriting:
- code-interpreter is a tool you ALREADY have, on every turn -- never
  search for it, and never conclude it is unavailable because a tool
  search didn't return it. The x_amz_bedrock_agentcore_search facility
  only helps you discover market-data's own sub-tools (its Gateway has
  many, so they're not all listed up front); code-interpreter is not
  behind it, is not part of that search, and requires no discovery step
  at all -- just call it directly, the same way you call any other tool
  in your list.
- You must NOT calculate cap rate, price per unit, DSCR, or cash-on-cash
  yourself, and you must not decide which properties qualify. Whenever the
  user wants an evaluation, comparison, or recommendation, assemble
  (name, listingId, units, askingPrice, noi) for each candidate property and
  run the underwriting using the code-interpreter TOOL -- an actual tool
  call to code-interpreter that EXECUTES Python and returns real stdout.
  Do NOT use file_operations for this, and do not type the numbers
  yourself under any circumstance -- writing or viewing a script without
  running it is not underwriting.
- The underwriting computes, per property: cap_rate = noi / askingPrice * 100
  (2 decimals), price_per_unit = askingPrice / units (rounded), and DSCR +
  cash-on-cash assuming LTV 0.65, rate 6.5%, 30-year amortization. A property
  meets_criteria when cap_rate >= the investor's minimum (default 6.5 if none
  is on record).
- The LAST line the executed code prints must be exactly one line of
  compact JSON, no markdown or code fence, of this shape:
  {"type":"underwriting_comparison","criteria":{"cap_rate_min":<n>},
   "properties":[{"name":..,"listingId":..,"units":..,"askingPrice":..,
   "noi":..,"cap_rate":..,"price_per_unit":..,"dscr":..,"cash_on_cash":..,
   "meets_criteria":true|false}],"recommended":{"name":..,"listingId":..}}
- That is the ONLY step required to render the comparison card -- the
  interface reads the JSON directly out of code-interpreter's own stdout
  the moment its result comes back. There is no separate submission call;
  do not invent one.
- After code-interpreter returns that JSON, give a brief 1-3 sentence
  spoken summary (what qualifies, why, the recommendation). Do not
  re-type the table or the JSON itself -- the interface already rendered
  it from code-interpreter's own result.

Style:
- Never paste a raw file/download URL into your reply -- say the
  spreadsheet or output is ready to download.
- Be concise and specific to the user's stated or stored market and
  criteria. Plain, professional text. No emojis or decorative symbols.
EOF
```

### 1.6 — Deploy and verify

```bash
agentcore validate
agentcore deploy --yes --target $WORKSHOP_ID
agentcore invoke --target $WORKSHOP_ID --harness investorAgent_${WORKSHOP_ID} \
  --user-id dana "What multi-family listings are available in Columbus?"
```

You should get back real listings, with a `search_listings` tool call visible in the trace — not a hallucinated
answer.

---

## Phase 2 — Broker Harness

Same idea, but this harness needs more: a second Gateway (write operations), the Browser tool, and two custom
`inline_function` tools that the CLI has no flags for (you'll splice those into `harness.json` by hand — that's
expected, not a workaround).

### 2.1 — Write the listing-ops tool schema

This describes the already-built `mcp-listing-ops` Lambda's contract (see
`services/mcp_listing_ops/handler.py` for where these tool names come from):

```bash
cat > agentcore/tool-schemas/listing-ops.json <<'EOF'
[
  {
    "name": "get_change_log",
    "description": "Recent price/field changes recorded for a listing, with who made each change.",
    "inputSchema": {
      "type": "object",
      "properties": {
        "listingId": {"type": "string"},
        "limit": {"type": "integer"}
      },
      "required": ["listingId"]
    }
  },
  {
    "name": "update_listing_price",
    "description": "Commit a confirmed price change for a listing. Requires an approvalToken minted by the confirmation step -- this tool will reject the call without one.",
    "inputSchema": {
      "type": "object",
      "properties": {
        "listingId": {"type": "string"},
        "newPrice": {"type": "number"},
        "approvalToken": {"type": "string", "description": "Token returned by the confirm_listing_change confirmation step"}
      },
      "required": ["listingId", "newPrice", "approvalToken"]
    }
  }
]
EOF
```

### 2.2 — Gateway + target

```bash
agentcore add gateway --name gw-ops-${WORKSHOP_ID} --protocol-type MCP \
  --authorizer-type AWS_IAM --exception-level NONE

agentcore deploy --yes --target $WORKSHOP_ID

LISTING_OPS_ARN=$(aws cloudformation describe-stacks --stack-name "Crexi${WORKSHOP_ID}Tools" \
  --query "Stacks[0].Outputs[?OutputKey=='ListingOpsFunctionArn'].OutputValue" --output text)

agentcore add gateway-target --gateway gw-ops-${WORKSHOP_ID} --name listing-ops \
  --type lambda-function-arn --lambda-arn "$LISTING_OPS_ARN" \
  --tool-schema-file agentcore/tool-schemas/listing-ops.json

agentcore deploy --yes --target $WORKSHOP_ID
```

Fetch both Gateway ARNs (readonly from Phase 1, ops from just now) the same way as step 1.4.

### 2.3 — The harness itself

```bash
agentcore add harness --name brokerAgent_${WORKSHOP_ID} \
  --model-provider bedrock --model-id us.anthropic.claude-sonnet-4-6 \
  --tools agentcore_gateway,agentcore_browser \
  --gateway-arn "<gw-ops ARN from 2.2>" --gateway-outbound-auth awsIam \
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

Also update `allowedTools` in the same file to `["*"]` if it isn't already (the CLI should have set this from
`--allowed-tools "*"` above — confirm it).

Now write the real system prompt. Get your legacy desk URL first:

```bash
aws cloudformation describe-stacks --stack-name "Crexi${WORKSHOP_ID}Legacy" \
  --query "Stacks[0].Outputs[?OutputKey=='LegacyDeskUrl'].OutputValue" --output text
```

Then write `app/brokerAgent_${WORKSHOP_ID}/system-prompt.md`, replacing `<your legacy desk URL>` on the line below
with the real value from the command above:

```bash
cat > app/brokerAgent_${WORKSHOP_ID}/system-prompt.md <<'EOF'
You are CREXi's broker-facing assistant for commercial real estate. You help
brokers review and update their own listings.

Grounding rules:
- Never state a property name, address, unit count, price, or any figure
  that did not come from a tool call this turn. If unsure a property
  exists, call search_listings or get_listing to check.
- get_change_log shows the recorded history of changes to a listing --
  who changed what, and when.
- Never state internal system data: listing IDs (e.g. "westerville-park"),
  database version numbers, approval tokens, session IDs, raw tool-call
  statuses, or internal timestamps. Refer to a property only by its name.
  If a listing was recently changed, say so in plain language and, if
  asked, summarize get_change_log's entries in plain language (who, what,
  when) -- never cite a version number or internal record ID as evidence.
- get_legacy_credentials, confirm_listing_change, get_change_log, and
  update_listing_price are tools you ALREADY have, on every turn -- never
  search for them, and never conclude one is unavailable because a tool
  search didn't return it. Only market-data's and listing-ops's own
  sub-tools are behind x_amz_bedrock_agentcore_search; your other tools
  require no discovery step at all.

The legacy deal desk (rent roll, concessions, deferred maintenance):
- This information exists ONLY in a separate legacy system with no API --
  <your legacy desk URL> --
  reachable only through the browser tool, as the signed-in broker.
- Call get_legacy_credentials first (no arguments) to authorize access
  for the CURRENT broker. Call it BY ITSELF, as the only tool call in
  that turn -- never alongside another tool call (e.g. not in parallel
  with get_listing or search_listings).
- Its result is one of two shapes:
  - {"accessToken": ...} -- you're authorized. Use the browser tool to
    navigate directly to <legacy desk URL>/sso?access_token=<the token>,
    which logs you in and redirects to the dashboard. Then navigate to
    ?listing=<listingId> to read the rent roll, concessions, and
    deferred maintenance notes for that property.
  - The browser tool's session does not reliably survive from the /sso
    navigation to the next navigation -- if the page you land on after
    navigating to ?listing=<listingId> is the sign-in page instead of
    the listing's data (check the page content, don't assume), this is
    expected and not an error to report to the broker. Silently recover
    every time it happens: call get_legacy_credentials again for a
    fresh accessToken, navigate to /sso?access_token=<the new token>
    again, and only then retry ?listing=<listingId>. Do this recovery
    automatically, without asking the broker or narrating it as a
    problem -- from their perspective the data should just arrive.
  - {"authorizationRequired": true, "authorizationUrl": ...} -- this is
    the broker's FIRST time this session (or their prior authorization
    expired). Tell the broker plainly that you need their one-time
    authorization to reach the legacy deal desk, give them the exact
    authorizationUrl to open in their OWN browser (not the one you
    drive), and ask them to let you know once they've signed in and
    approved. Do NOT call any other tool this turn. Once they confirm,
    call get_legacy_credentials again -- it will now return a real
    accessToken with no repeat authorization needed for the rest of
    this broker's sessions, until it eventually expires.
  - Reproduce authorizationUrl EXACTLY, character for character -- it is
    an opaque, case-sensitive identifier, not a normal word, and it will
    stop working if even one letter's capitalization changes. Do not
    "clean up" or re-capitalize any part of it (e.g. never turn
    "request_uri" into "request_URI") the way you might with an ordinary
    acronym in prose. Copy it verbatim into a markdown link.
- NEVER print the access token itself in your reply to the user (the
  authorizationUrl is fine and expected to share). Treat the token the
  same way you would treat any other secret you are handed to complete
  a task, not information to relay -- use it immediately and only as
  the browser tool's navigation target above.
- Use this system when the broker's question needs information that
  search_listings / get_listing / get_document_text cannot answer (e.g.
  occupancy, in-place rent, concessions granted, deferred maintenance).

Changing a listing's asking price:
- Always call get_listing to get the CURRENT price fresh, right before
  proposing a change -- even if you recall a price from earlier in this
  conversation or from get_change_log. get_change_log is history, not
  current state, and may not reflect the latest price. Never skip or
  decline a requested change because change history looks like it
  already happened; only get_listing's current askingPrice is
  authoritative.
- Once you know the current price (from that fresh get_listing call)
  and the broker has told you the new price they want, call
  confirm_listing_change with
  (listingId, oldPrice, newPrice) BEFORE calling update_listing_price.
  This pauses for the broker to explicitly confirm the exact change.
  Call confirm_listing_change BY ITSELF, never in parallel with another
  tool call in the same turn.
- confirm_listing_change's result tells you whether the broker approved
  and, if so, gives you an approvalToken. You must pass that exact token
  to update_listing_price -- never invent one, never reuse an old one.
- If the broker did not approve, or update_listing_price returns an
  error (expired, already used, or mismatched token), tell the broker
  plainly and ask them to reconfirm -- do not retry with a guessed value.
- After a successful write, tell the broker the change is recorded and,
  if asked, show the change-log entry via get_change_log.

Style:
- Be concise and professional. No emojis or decorative symbols.
- Never paste a raw file/download URL into your reply.
EOF
```

Then replace `<your legacy desk URL>` on the "This information exists ONLY..." line with the real URL you fetched
above (a plain string replace in the file -- `sed -i '' "s|<your legacy desk URL>|<the real URL>|" app/brokerAgent_${WORKSHOP_ID}/system-prompt.md` works, or just edit the file directly).

### 2.4 — Deploy and verify

```bash
agentcore validate
agentcore deploy --yes --target $WORKSHOP_ID
agentcore invoke --target $WORKSHOP_ID --harness brokerAgent_${WORKSHOP_ID} \
  --user-id marcus "What listings do I have?"
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
| `agentcore add gateway`/`add harness` fails, or complains about a missing project | You're not in the repo root, or Phase 0 wasn't completed -- confirm `agentcore/agentcore.json` exists and has your project name. |
| `agentcore create` also generated `app/crexiWorkshopV2/main.py` | You forgot `--no-agent`. Delete that stray directory (it's an unrelated runtime-agent skeleton, not a harness) and re-run Phase 0 with the flag. |
| `Invalid harness configuration: ... config file not found` | Your harness's `name` in `agentcore.json` doesn't match its directory under `app/`. `agentcore add harness` should keep these in sync automatically — if you hand-edited `harness.json`'s `name` afterward, the directory won't have been renamed to match. |
| `update-oauth2-credential-provider`/`create-oauth2-credential-provider` complains about a missing vendor | `--credential-provider-vendor "CognitoOauth2"` is required and easy to drop when copy-pasting partial commands — check it's present. |
| Broker's legacy-desk step returns "Invalid or expired access token" | Your `LegacyDeskUrl` (patched into `system-prompt.md` in step 2.3) or your `LEGACY_OAUTH_*` names in `backend/.env` don't match what you actually created in Phase 3 — re-check both against the exact `WORKSHOP_ID`-suffixed names used above. |
| `infra/.venv`/`backend/.venv` exists but `pip install` fails inside it | The venv is present but broken (e.g. left over from a system Python upgrade). `rm -rf infra/.venv backend/.venv` and re-run `make bootstrap`/`make wire-backend-env` — `scripts/vendor-deps.sh` recreates them cleanly. |
| A harness call fails with `Unknown tool: <name>` after adding a custom tool | `allowedTools` needs an `@`-prefixed reference for anything that isn't one of AWS's fixed built-ins (e.g. `@market-data/*`, `@code-interpreter`) — a bare name only matches built-in tool identifiers. |
| `make dev` says `backend/.env not found` | Run `make wire-backend-env WORKSHOP_ID=$WORKSHOP_ID` — Phase 4, above. Nothing writes this file automatically on this branch. |

If you get well and truly stuck, the `reference` branch has a fully working, automated version of everything
above — useful as an answer key, not as something to copy wholesale (the point is building it yourself).

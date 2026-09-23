"""Central config, read from environment. Populated by
scripts/wire-backend-env.sh after `cdk deploy` + `agentcore deploy`
(reads their outputs and writes backend/.env) -- see that script for
where each value actually comes from.
"""
import os

WORKSHOP_ID = os.environ.get("WORKSHOP_ID", "dev01")
AWS_REGION = os.environ.get("AWS_REGION", "us-west-2")

INVESTOR_HARNESS_ARN = os.environ.get(
    "INVESTOR_HARNESS_ARN",
    "arn:aws:bedrock-agentcore:us-west-2:347272280436:harness/crexiWorkshopV2_investorAgent-2ebkyHVXzc",
)
BROKER_HARNESS_ARN = os.environ.get(
    "BROKER_HARNESS_ARN",
    "arn:aws:bedrock-agentcore:us-west-2:347272280436:harness/crexiWorkshopV2_brokerAgent-Zh8tLOhxvX",
)

COGNITO_USER_POOL_ID = os.environ.get("COGNITO_USER_POOL_ID", "us-west-2_KYy68lcCk")
COGNITO_APP_CLIENT_ID = os.environ.get("COGNITO_APP_CLIENT_ID", "4fg4n26sc6adgghku4vcdulnod")

LISTINGS_TABLE = os.environ.get("LISTINGS_TABLE", f"crexi-{WORKSHOP_ID}-listings")
APPROVALS_TABLE = os.environ.get("APPROVALS_TABLE", f"crexi-{WORKSHOP_ID}-approvals")
# The real bucket name is account+region-suffixed (see infra/stacks/data_stack.py);
# ARTIFACTS_BUCKET must come from backend/.env in any real deployment --
# there is no account ID that could be a correct default here, so the
# fallback is deliberately obviously-wrong rather than pointing at a
# specific real account.
ARTIFACTS_BUCKET = os.environ.get(
    "ARTIFACTS_BUCKET", f"crexi-{WORKSHOP_ID}-docs-000000000000-{AWS_REGION}"
)

APPROVAL_TOKEN_TTL_SECONDS = int(os.environ.get("APPROVAL_TOKEN_TTL_SECONDS", "120"))

# The frontend's own dev-server origin -- CORS must allow it explicitly.
# Comma-separated if you ever need more than one (e.g. a deployed URL
# alongside local dev). Defaults to Vite's own default port, matching
# what `make dev` always launches, but is not hardcoded for anyone
# running the frontend on a different port or host.
CORS_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("CORS_ALLOWED_ORIGINS", "http://localhost:5173").split(",")
    if origin.strip()
]

# Group name -> which harness a session gets routed to. This is the
# application-layer access-control decision: the backend always invokes
# the harness that matches the caller's real Cognito group, never a
# harness the model or the client asks for.
GROUP_TO_HARNESS_ARN = {
    "investors": INVESTOR_HARNESS_ARN,
    "brokers": BROKER_HARNESS_ARN,
}

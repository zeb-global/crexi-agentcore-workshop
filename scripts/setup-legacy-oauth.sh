#!/usr/bin/env bash
# Provisions the two AgentCore Identity resources Checkpoint 4 / Legacy
# Portal OAuth needs -- a workload identity and an OAuth2 credential
# provider pointing at the LegacyOAuthAppClient from identity_stack.py --
# and wires the resulting Cognito/workload callback URLs together. Called
# from wire-backend-env.sh, not make bootstrap directly, because it needs
# backend/.env's own LEGACY_OAUTH_RETURN_URL value (the backend's own
# callback route) as one of its inputs.
#
# On the REFERENCE branch this is fully automated -- there is nothing for
# a reviewer to do by hand here. On the participant workshop branch, this
# script does NOT run; participants create these two resources themselves
# via the walkthrough's copy-paste commands, because that hands-on step
# (not this one) is the actual AgentCore Identity teaching moment. Keep
# both paths creating resources with the SAME shape so the walkthrough's
# commands and this script never drift apart.
#
# Idempotent -- safe to re-run (checks for existing resources by name
# before creating).
set -euo pipefail
cd "$(dirname "$0")/.."

WORKSHOP_ID="${1:?Usage: scripts/setup-legacy-oauth.sh <WORKSHOP_ID> <LEGACY_OAUTH_RETURN_URL>}"
RETURN_URL="${2:?Usage: scripts/setup-legacy-oauth.sh <WORKSHOP_ID> <LEGACY_OAUTH_RETURN_URL>}"
REGION="${AWS_REGION:-us-west-2}"

IDENTITY_STACK="Crexi${WORKSHOP_ID}Identity"
out() { aws cloudformation describe-stacks --stack-name "$IDENTITY_STACK" --region "$REGION" \
  --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text; }

USER_POOL_ID=$(out UserPoolId)
CLIENT_ID=$(out LegacyOAuthClientId)
ISSUER=$(out LegacyOAuthIssuer)
AUTH_ENDPOINT=$(out LegacyOAuthAuthorizationEndpoint)
TOKEN_ENDPOINT=$(out LegacyOAuthTokenEndpoint)
CLIENT_SECRET=$(aws cognito-idp describe-user-pool-client --user-pool-id "$USER_POOL_ID" \
  --client-id "$CLIENT_ID" --region "$REGION" --query 'UserPoolClient.ClientSecret' --output text)

WORKLOAD_NAME="crexi${WORKSHOP_ID}legacyoauth"
PROVIDER_NAME="crexi${WORKSHOP_ID}legacyoauth"

if ! aws bedrock-agentcore-control get-workload-identity --name "$WORKLOAD_NAME" --region "$REGION" >/dev/null 2>&1; then
  aws bedrock-agentcore-control create-workload-identity --name "$WORKLOAD_NAME" --region "$REGION" >/dev/null
  echo "Created workload identity $WORKLOAD_NAME."
else
  echo "Workload identity $WORKLOAD_NAME already exists, reusing."
fi
aws bedrock-agentcore-control update-workload-identity --name "$WORKLOAD_NAME" \
  --allowed-resource-oauth2-return-urls "$RETURN_URL" --region "$REGION" >/dev/null

PROVIDER_CONFIG=$(python3 -c "
import json
print(json.dumps({'includedOauth2ProviderConfig': {
    'clientId': '$CLIENT_ID', 'clientSecret': '$CLIENT_SECRET',
    'issuer': '$ISSUER', 'authorizationEndpoint': '$AUTH_ENDPOINT',
    'tokenEndpoint': '$TOKEN_ENDPOINT',
}}))
")

if aws bedrock-agentcore-control get-oauth2-credential-provider --name "$PROVIDER_NAME" --region "$REGION" >/dev/null 2>&1; then
  echo "Credential provider $PROVIDER_NAME already exists, updating with current Cognito values."
  aws bedrock-agentcore-control update-oauth2-credential-provider --name "$PROVIDER_NAME" \
    --credential-provider-vendor "CognitoOauth2" \
    --oauth2-provider-config-input "$PROVIDER_CONFIG" --region "$REGION" >/dev/null
  CALLBACK_URL=$(aws bedrock-agentcore-control get-oauth2-credential-provider --name "$PROVIDER_NAME" \
    --region "$REGION" --query 'callbackUrl' --output text)
else
  CRED_JSON=$(aws bedrock-agentcore-control create-oauth2-credential-provider --name "$PROVIDER_NAME" \
    --credential-provider-vendor "CognitoOauth2" --oauth2-provider-config-input "$PROVIDER_CONFIG" --region "$REGION")
  CALLBACK_URL=$(echo "$CRED_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin)['callbackUrl'])")
  echo "Created credential provider $PROVIDER_NAME."
fi

# update-user-pool-client replaces the WHOLE OAuth config, not just the
# callback list -- re-specify every setting identity_stack.py originally
# set, or this silently clobbers the client's OAuth flows/scopes.
aws cognito-idp update-user-pool-client \
  --user-pool-id "$USER_POOL_ID" --client-id "$CLIENT_ID" \
  --allowed-o-auth-flows "code" --allowed-o-auth-scopes "openid" "email" \
  --allowed-o-auth-flows-user-pool-client --supported-identity-providers "COGNITO" \
  --callback-urls "https://example.com/callback" "$CALLBACK_URL" \
  --region "$REGION" >/dev/null

echo "LEGACY_OAUTH_WORKLOAD_NAME=${WORKLOAD_NAME}"
echo "LEGACY_OAUTH_PROVIDER_NAME=${PROVIDER_NAME}"

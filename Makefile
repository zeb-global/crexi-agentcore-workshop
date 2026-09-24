# CREXi AgentCore Workshop -- one command per lifecycle step.
# WORKSHOP_ID is required everywhere; every physical resource name is
# namespaced by it so participants can safely share one AWS account.

SHELL := /bin/bash
WORKSHOP_ID ?=
WORKSHOP_SECRET ?=
AWS_REGION ?= us-west-2
export AWS_REGION
export AWS_DEFAULT_REGION := $(AWS_REGION)
export JSII_SILENCE_WARNING_DEPRECATED_NODE_VERSION := 1

INFRA_VENV := infra/.venv/bin/activate

.PHONY: preflight bootstrap deploy seed dev verify destroy vendor-deps wire-backend-env

preflight:
	@bash scripts/preflight.sh

vendor-deps:
	@bash scripts/vendor-deps.sh

# This is the WORKSHOP branch's bootstrap -- CDK stacks only
# (data/identity/legacy/tools/observability). It deliberately stops here:
# everything AgentCore-native (gateways, harnesses, the Legacy Portal OAuth
# workload identity/credential provider) is built by hand, per WALKTHROUGH.md
# -- that hands-on work is the actual point of the workshop. Compare the
# REFERENCE branch's Makefile, where this same target goes on to do all of
# that automatically.
bootstrap: vendor-deps
	@test -n "$(WORKSHOP_ID)" || (echo "Usage: make bootstrap WORKSHOP_ID=<id> WORKSHOP_SECRET=<secret>"; exit 1)
	@test -n "$(WORKSHOP_SECRET)" || (echo "WORKSHOP_SECRET is required"; exit 1)
	source $(INFRA_VENV) && cd infra && \
		WORKSHOP_ID=$(WORKSHOP_ID) WORKSHOP_SECRET=$(WORKSHOP_SECRET) \
		CDK_DEFAULT_ACCOUNT=$$(aws sts get-caller-identity --query Account --output text) \
		CDK_DEFAULT_REGION=$(AWS_REGION) \
		cdk deploy --all --require-approval never
	WORKSHOP_ID=$(WORKSHOP_ID) bash scripts/ensure-aws-target.sh
	@echo ""
	@echo "Base infrastructure deployed. Next: open WALKTHROUGH.md and build your"
	@echo "gateways, harnesses, and Legacy Portal OAuth setup by hand."

# On the workshop branch this is a plain passthrough to the AgentCore CLI --
# use it after any harness/gateway config change you make by hand, per
# WALKTHROUGH.md. Nothing to render first; you already named everything
# yourself when you created it.
deploy:
	@test -n "$(WORKSHOP_ID)" || (echo "Usage: make deploy WORKSHOP_ID=<id>"; exit 1)
	agentcore deploy --yes --target $(WORKSHOP_ID)

# Re-seeds listings/comps/documents/legacy records to opening state without
# a full cdk deploy -- for a pair that wrecks their data mid-checkpoint.
seed:
	@test -n "$(WORKSHOP_ID)" || (echo "Usage: make seed WORKSHOP_ID=<id>"; exit 1)
	aws lambda invoke --function-name crexi-$(WORKSHOP_ID)-seed-data --payload '{"RequestType":"Update"}' --cli-binary-format raw-in-base64-out /tmp/seed_reset.json
	aws lambda invoke --function-name crexi-$(WORKSHOP_ID)-seed-legacy --payload '{"RequestType":"Update"}' --cli-binary-format raw-in-base64-out /tmp/seed_legacy_reset.json
	@echo "Reset to opening state."

# Writes backend/.env (harness ARNs, Cognito pool/client, table names) for
# this participant. backend/config.py's fallback values are dev01's -- not a
# usable default for anyone else -- so this must be run before `make dev`.
wire-backend-env:
	@test -n "$(WORKSHOP_ID)" || (echo "Usage: make wire-backend-env WORKSHOP_ID=<id>"; exit 1)
	bash scripts/wire-backend-env.sh $(WORKSHOP_ID)

dev:
	@test -f backend/.env || (echo "backend/.env not found -- run: make wire-backend-env WORKSHOP_ID=<id>"; exit 1)
	@echo "Starting FastAPI backend (:8000) and Vite frontend (:5173)..."
	@(cd backend && source .venv/bin/activate && set -a && source .env && set +a && uvicorn main:app --reload --port 8000 &)
	@(cd frontend && npm run dev)

verify:
	@bash scripts/verify.sh

# Tears down only THIS participant's harness/gateway stack -- never
# `agentcore remove all` + redeploy, which would reset the shared
# agentcore.json resource definitions that every other participant's target
# still deploys from.
destroy:
	@test -n "$(WORKSHOP_ID)" || (echo "Usage: make destroy WORKSHOP_ID=<id>"; exit 1)
	aws cloudformation delete-stack --stack-name AgentCore-crexiWorkshopV2-$(WORKSHOP_ID)
	aws cloudformation wait stack-delete-complete --stack-name AgentCore-crexiWorkshopV2-$(WORKSHOP_ID)
	WORKSHOP_ID=$(WORKSHOP_ID) bash scripts/remove-aws-target.sh
	source $(INFRA_VENV) && cd infra && \
		WORKSHOP_ID=$(WORKSHOP_ID) \
		CDK_DEFAULT_ACCOUNT=$$(aws sts get-caller-identity --query Account --output text) \
		CDK_DEFAULT_REGION=$(AWS_REGION) \
		cdk destroy --all --force

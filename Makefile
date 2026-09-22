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

.PHONY: preflight bootstrap deploy seed dev verify destroy vendor-deps

preflight:
	@bash scripts/preflight.sh

vendor-deps:
	@bash scripts/vendor-deps.sh

# Full path: our CDK (data/identity/legacy/tools/observability), then the
# AgentCore CLI's own deploy (gateways, targets, memory, harnesses).
bootstrap: vendor-deps
	@test -n "$(WORKSHOP_ID)" || (echo "Usage: make bootstrap WORKSHOP_ID=<id> WORKSHOP_SECRET=<secret>"; exit 1)
	@test -n "$(WORKSHOP_SECRET)" || (echo "WORKSHOP_SECRET is required"; exit 1)
	source $(INFRA_VENV) && cd infra && \
		WORKSHOP_ID=$(WORKSHOP_ID) WORKSHOP_SECRET=$(WORKSHOP_SECRET) \
		CDK_DEFAULT_ACCOUNT=$$(aws sts get-caller-identity --query Account --output text) \
		CDK_DEFAULT_REGION=$(AWS_REGION) \
		cdk deploy --all --require-approval never
	agentcore deploy --yes

deploy:
	agentcore deploy --yes

# Re-seeds listings/comps/documents/legacy records to opening state without
# a full cdk deploy -- for a pair that wrecks their data mid-checkpoint.
seed:
	@test -n "$(WORKSHOP_ID)" || (echo "Usage: make seed WORKSHOP_ID=<id>"; exit 1)
	aws lambda invoke --function-name crexi-$(WORKSHOP_ID)-seed-data --payload '{"RequestType":"Update"}' --cli-binary-format raw-in-base64-out /tmp/seed_reset.json
	aws lambda invoke --function-name crexi-$(WORKSHOP_ID)-seed-legacy --payload '{"RequestType":"Update"}' --cli-binary-format raw-in-base64-out /tmp/seed_legacy_reset.json
	@echo "Reset to opening state."

dev:
	@echo "Starting FastAPI backend (:8000) and Vite frontend (:5173)..."
	@(cd backend && source .venv/bin/activate && uvicorn main:app --reload --port 8000 &) 
	@(cd frontend && npm run dev)

verify:
	@bash scripts/verify.sh

destroy:
	@test -n "$(WORKSHOP_ID)" || (echo "Usage: make destroy WORKSHOP_ID=<id>"; exit 1)
	agentcore remove all
	agentcore deploy --yes
	source $(INFRA_VENV) && cd infra && \
		WORKSHOP_ID=$(WORKSHOP_ID) \
		CDK_DEFAULT_ACCOUNT=$$(aws sts get-caller-identity --query Account --output text) \
		CDK_DEFAULT_REGION=$(AWS_REGION) \
		cdk destroy --all --force

#!/usr/bin/env python3
"""CDK entrypoint for the CREXi workshop's non-AgentCore infrastructure.

Everything AgentCore-native (harnesses, gateways, Lambda tool targets, managed
memory, credential providers) is declared in agentcore/agentcore.json and
deployed by `agentcore deploy`. This CDK app only owns what the AgentCore CLI
has no concept of: DynamoDB, S3, Cognito, the legacy deal desk, and the seeder.
"""
import os

import aws_cdk as cdk

from stacks.data_stack import DataStack
from stacks.identity_stack import IdentityStack
from stacks.legacy_stack import LegacyStack
from stacks.observability_stack import ObservabilityStack

WORKSHOP_ID = os.environ.get("WORKSHOP_ID")
if not WORKSHOP_ID:
    raise SystemExit(
        "WORKSHOP_ID is required, e.g.:\n"
        "  WORKSHOP_ID=dev01 cdk deploy --all\n"
        "Every physical resource name is namespaced by this value so that "
        "multiple participants can safely share one AWS account."
    )
if not WORKSHOP_ID.isalnum() or not WORKSHOP_ID[0].isalpha():
    raise SystemExit(
        f"WORKSHOP_ID={WORKSHOP_ID!r} must start with a letter and contain "
        "only letters and digits (it is embedded in Cognito, S3, and "
        "AgentCore resource names, each with their own charset rules)."
    )

env = cdk.Environment(
    account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
    region=os.environ.get("CDK_DEFAULT_REGION", "us-west-2"),
)

app = cdk.App()
cdk.Tags.of(app).add("WorkshopId", WORKSHOP_ID)
cdk.Tags.of(app).add("Project", "crexi-agentcore-workshop")

data = DataStack(app, f"Crexi{WORKSHOP_ID}Data", workshop_id=WORKSHOP_ID, env=env)
identity = IdentityStack(app, f"Crexi{WORKSHOP_ID}Identity", workshop_id=WORKSHOP_ID, env=env)
legacy = LegacyStack(
    app,
    f"Crexi{WORKSHOP_ID}Legacy",
    workshop_id=WORKSHOP_ID,
    listings_table=data.listings_table,
    env=env,
)
ObservabilityStack(
    app,
    f"Crexi{WORKSHOP_ID}Observability",
    workshop_id=WORKSHOP_ID,
    env=env,
)

app.synth()

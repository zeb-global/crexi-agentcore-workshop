"""Enables CloudWatch Transaction Search once per account/region so AgentCore
traces (model calls, memory ops, gateway/tool calls, Browser and Code
Interpreter sessions) are queryable in the GenAI Observability dashboard
from the harnesses' first invocation, with no instrumentation code.

Account-level and idempotent to enable, but AWS says it must be *disabled*
before CDK/CloudFormation enables it -- so if two participants share an
account, only the first person's deploy should create this. Rather than
relying on a human to know they're "not first" and pass a flag, this stack
asks X-Ray directly at synth time whether Transaction Search is already
active in this account/region and skips itself if so -- this was a real bug:
an earlier version of this docstring described a SKIP_OBSERVABILITY env var
that no Makefile target ever actually set, so it silently never skipped.
"""
import boto3
from aws_cdk import Stack, aws_logs as logs, aws_xray as xray
from constructs import Construct


def _transaction_search_already_active(region: str) -> bool:
    status = boto3.client("xray", region_name=region).get_trace_segment_destination()
    return status.get("Status") == "ACTIVE"


class ObservabilityStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, *, workshop_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        if _transaction_search_already_active(self.region):
            return

        logs.CfnResourcePolicy(
            self,
            "TransactionSearchLogsPolicy",
            policy_name="TransactionSearchAccess",
            policy_document=(
                '{"Version":"2012-10-17","Statement":[{"Sid":"TransactionSearchXRayAccess",'
                '"Effect":"Allow","Principal":{"Service":"xray.amazonaws.com"},'
                '"Action":"logs:PutLogEvents","Resource":['
                f'"arn:aws:logs:{self.region}:{self.account}:log-group:aws/spans:*",'
                f'"arn:aws:logs:{self.region}:{self.account}:log-group:/aws/application-signals/data:*"'
                '],"Condition":{"ArnLike":{"aws:SourceArn":'
                f'"arn:aws:xray:{self.region}:{self.account}:*"}},'
                f'"StringEquals":{{"aws:SourceAccount":"{self.account}"}}}}]}}'
            ),
        )

        xray.CfnTransactionSearchConfig(
            self,
            "TransactionSearchConfig",
            indexing_percentage=100,
        )

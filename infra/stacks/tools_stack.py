"""The two MCP tool Lambdas: crexi-{id}-mcp-market-data (read) and
crexi-{id}-mcp-listing-ops (write, approval-token gated).

Registered as `lambda-function-arn` gateway targets via the AgentCore CLI
(`agentcore add gateway-target`), which wires the gateway service role's
lambda:InvokeFunction permission on these ARNs -- see
https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-prerequisites-permissions.html
"Access a Lambda function". This stack only owns the Lambdas themselves;
Gateway/target config lives in agentcore/agentcore.json.
"""
from aws_cdk import (
    CfnOutput,
    Duration,
    Stack,
    aws_dynamodb as dynamodb,
    aws_lambda as _lambda,
    aws_logs as logs,
    aws_s3 as s3,
)
from constructs import Construct


class ToolsStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        workshop_id: str,
        listings_table: dynamodb.ITable,
        changelog_table: dynamodb.ITable,
        approvals_table: dynamodb.ITable,
        docs_bucket: s3.IBucket,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.market_data_fn = _lambda.Function(
            self,
            "MarketDataFunction",
            function_name=f"crexi-{workshop_id}-mcp-market-data",
            runtime=_lambda.Runtime.PYTHON_3_13,
            architecture=_lambda.Architecture.ARM_64,
            handler="handler.lambda_handler",
            # pypdf is vendored directly into services/mcp_market_data/ (pure-Python
            # wheel, no compiled extensions -- confirmed no .so/.pyd files) rather than
            # installed via Docker bundling, matching this repo's no-Docker constraint.
            code=_lambda.Code.from_asset("../services/mcp_market_data"),
            timeout=Duration.seconds(20),
            memory_size=256,
            log_retention=logs.RetentionDays.ONE_WEEK,
            environment={
                "LISTINGS_TABLE": listings_table.table_name,
                "DOCS_BUCKET": docs_bucket.bucket_name,
            },
        )
        listings_table.grant_read_data(self.market_data_fn)
        docs_bucket.grant_read(self.market_data_fn)

        self.listing_ops_fn = _lambda.Function(
            self,
            "ListingOpsFunction",
            function_name=f"crexi-{workshop_id}-mcp-listing-ops",
            runtime=_lambda.Runtime.PYTHON_3_13,
            architecture=_lambda.Architecture.ARM_64,
            handler="handler.lambda_handler",
            code=_lambda.Code.from_asset("../services/mcp_listing_ops"),
            timeout=Duration.seconds(20),
            memory_size=256,
            log_retention=logs.RetentionDays.ONE_WEEK,
            environment={
                "LISTINGS_TABLE": listings_table.table_name,
                "CHANGELOG_TABLE": changelog_table.table_name,
                "APPROVALS_TABLE": approvals_table.table_name,
            },
        )
        listings_table.grant_read_write_data(self.listing_ops_fn)
        changelog_table.grant_write_data(self.listing_ops_fn)
        approvals_table.grant_read_write_data(self.listing_ops_fn)

        CfnOutput(self, "MarketDataFunctionArn", value=self.market_data_fn.function_arn)
        CfnOutput(self, "ListingOpsFunctionArn", value=self.listing_ops_fn.function_arn)

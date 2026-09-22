"""DynamoDB tables, the documents/comps/artifacts bucket, and the seeder.

The seeder is a CDK custom resource so `cdk deploy` alone leaves the account
in "opening state" for the scenario: the three Columbus listings loaded,
comps JSON uploaded, T-12/OM PDFs generated and uploaded, with no separate
`make seed` step required (though `make seed` re-runs it on demand too).
"""
from aws_cdk import (
    CustomResource,
    Duration,
    RemovalPolicy,
    Stack,
    aws_dynamodb as dynamodb,
    aws_iam as iam,
    aws_lambda as _lambda,
    aws_logs as logs,
    aws_s3 as s3,
    custom_resources as cr,
)
from constructs import Construct


class DataStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, *, workshop_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        self.workshop_id = workshop_id

        # ---- DynamoDB: listings ------------------------------------------------
        self.listings_table = dynamodb.Table(
            self,
            "ListingsTable",
            table_name=f"crexi-{workshop_id}-listings",
            partition_key=dynamodb.Attribute(name="listingId", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
            point_in_time_recovery=False,
        )
        self.listings_table.add_global_secondary_index(
            index_name="market-assetType-index",
            partition_key=dynamodb.Attribute(name="marketAssetType", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="askingPrice", type=dynamodb.AttributeType.NUMBER),
        )

        # ---- DynamoDB: change log ----------------------------------------------
        self.changelog_table = dynamodb.Table(
            self,
            "ChangelogTable",
            table_name=f"crexi-{workshop_id}-changelog",
            partition_key=dynamodb.Attribute(name="listingId", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="changedAt", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
        )

        # ---- DynamoDB: approval tokens ------------------------------------------
        # Minted by the backend (which knows the real, validated Cognito
        # identity) after a broker confirms a price change. The listing-ops
        # MCP tool validates a token exists, is unexpired and unused, and
        # matches the exact write being attempted -- see
        # services/mcp_listing_ops/handler.py for why this exists instead
        # of trusting a model-supplied actor argument.
        self.approvals_table = dynamodb.Table(
            self,
            "ApprovalsTable",
            table_name=f"crexi-{workshop_id}-approvals",
            partition_key=dynamodb.Attribute(name="approvalToken", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
            time_to_live_attribute="expiresAt",
        )

        # ---- S3: documents, comps, artifacts -----------------------------------
        self.docs_bucket = s3.Bucket(
            self,
            "DocsBucket",
            bucket_name=f"crexi-{workshop_id}-docs-{self.account}-{self.region}",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
            enforce_ssl=True,
        )

        # ---- Seeder Lambda + custom resource -----------------------------------
        seed_fn = _lambda.Function(
            self,
            "SeedFunction",
            function_name=f"crexi-{workshop_id}-seed-data",
            runtime=_lambda.Runtime.PYTHON_3_13,
            architecture=_lambda.Architecture.ARM_64,
            handler="seed_handler.on_event",
            code=_lambda.Code.from_asset("../services/seed"),
            timeout=Duration.minutes(3),
            memory_size=512,
            log_retention=logs.RetentionDays.ONE_WEEK,
            environment={
                "LISTINGS_TABLE": self.listings_table.table_name,
                "DOCS_BUCKET": self.docs_bucket.bucket_name,
                "WORKSHOP_ID": workshop_id,
            },
        )
        self.listings_table.grant_write_data(seed_fn)
        self.docs_bucket.grant_write(seed_fn)

        provider = cr.Provider(self, "SeedProvider", on_event_handler=seed_fn)
        CustomResource(
            self,
            "SeedResource",
            service_token=provider.service_token,
            # Bumping this string forces a re-seed on the next `cdk deploy`
            # without needing `make seed` as a separate step.
            properties={"SeedVersion": "1"},
        )

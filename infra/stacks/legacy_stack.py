"""The legacy deal desk: a login-gated, no-API app with no path in except
AgentCore Browser driving a real form login as the signed-in broker.

Owns two small tables of its own (credentials, records) so it stays
self-contained and never shares a table with the listings/changelog data
the MCPs read — that separation is the point of the exercise.
"""
import os

from aws_cdk import (
    CfnOutput,
    CustomResource,
    Duration,
    RemovalPolicy,
    Stack,
    aws_cognito as cognito,
    aws_dynamodb as dynamodb,
    aws_lambda as _lambda,
    aws_logs as logs,
    custom_resources as cr,
)
from constructs import Construct


class LegacyStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        workshop_id: str,
        listings_table: dynamodb.ITable,
        oauth_user_pool: cognito.IUserPool,
        oauth_client_id: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.creds_table = dynamodb.Table(
            self,
            "LegacyCredsTable",
            table_name=f"crexi-{workshop_id}-legacy-creds",
            partition_key=dynamodb.Attribute(name="username", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
        )

        self.records_table = dynamodb.Table(
            self,
            "LegacyRecordsTable",
            table_name=f"crexi-{workshop_id}-legacy-records",
            partition_key=dynamodb.Attribute(name="listingId", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
        )

        self.app_fn = _lambda.Function(
            self,
            "LegacyAppFunction",
            function_name=f"crexi-{workshop_id}-legacy-deal-desk",
            runtime=_lambda.Runtime.PYTHON_3_13,
            architecture=_lambda.Architecture.ARM_64,
            handler="app.handler",
            code=_lambda.Code.from_asset("../services/legacy_deal_desk"),
            timeout=Duration.seconds(10),
            memory_size=256,
            log_retention=logs.RetentionDays.ONE_WEEK,
            environment={
                "CREDS_TABLE": self.creds_table.table_name,
                "RECORDS_TABLE": self.records_table.table_name,
                "LISTINGS_TABLE": listings_table.table_name,
                # Checkpoint 4 / Legacy Portal OAuth: /sso verifies tokens issued by
                # this pool's LegacyOAuthAppClient (see identity_stack.py). Real
                # per-user 3LO consent happens upstream via AgentCore Identity's
                # Token Vault -- this Lambda only ever verifies a token it's handed,
                # it never participates in the OAuth dance itself.
                "OAUTH_ISSUER": f"https://cognito-idp.{Stack.of(self).region}.amazonaws.com/{oauth_user_pool.user_pool_id}",
                "OAUTH_CLIENT_ID": oauth_client_id,
            },
        )
        self.creds_table.grant_read_data(self.app_fn)
        self.records_table.grant_read_data(self.app_fn)
        listings_table.grant_read_data(self.app_fn)

        self.fn_url = self.app_fn.add_function_url(
            auth_type=_lambda.FunctionUrlAuthType.NONE,
        )
        # Every harness's system-prompt.md literally names this URL as text
        # for the model to navigate the Browser tool to -- it was hardcoded
        # to whichever workshop deployed first, so every other participant's
        # broker harness tried to log into THAT workshop's legacy desk with
        # THEIR OWN credentials and failed. Each participant's own copy of
        # system-prompt.md needs this exact value patched in by hand (see
        # WORKSHOP_GUIDE.md's Phase 2) or, on the reference branch,
        # render_agentcore_config.py does it automatically.
        CfnOutput(self, "LegacyDeskUrl", value=self.fn_url.url)

        seed_fn = _lambda.Function(
            self,
            "LegacySeedFunction",
            function_name=f"crexi-{workshop_id}-seed-legacy",
            runtime=_lambda.Runtime.PYTHON_3_13,
            architecture=_lambda.Architecture.ARM_64,
            handler="legacy_seed_handler.on_event",
            code=_lambda.Code.from_asset("../services/seed"),
            timeout=Duration.minutes(2),
            log_retention=logs.RetentionDays.ONE_WEEK,
            environment={
                "CREDS_TABLE": self.creds_table.table_name,
                "RECORDS_TABLE": self.records_table.table_name,
                "WORKSHOP_ID": workshop_id,
                "WORKSHOP_SECRET": os.environ.get("WORKSHOP_SECRET", "changeme-" + workshop_id),
            },
        )
        self.creds_table.grant_write_data(seed_fn)
        self.records_table.grant_write_data(seed_fn)

        provider = cr.Provider(self, "LegacySeedProvider", on_event_handler=seed_fn)
        CustomResource(
            self,
            "LegacySeedResource",
            service_token=provider.service_token,
            properties={"SeedVersion": "1"},
        )

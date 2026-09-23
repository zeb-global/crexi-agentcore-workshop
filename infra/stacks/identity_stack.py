"""Cognito user pool: the inbound identity for both harnesses.

Two users only — dana@ (investors group) and marcus@ (brokers group) — with
passwords derived from WORKSHOP_SECRET so every account has the same login
without a secret being checked into git. The discovery URL feeds each
harness's customJwtAuthorizer in agentcore.json.
"""
import os

from aws_cdk import (
    CfnOutput,
    CustomResource,
    Duration,
    RemovalPolicy,
    Stack,
    aws_cognito as cognito,
    aws_lambda as _lambda,
    aws_logs as logs,
    custom_resources as cr,
)
from constructs import Construct


class IdentityStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, *, workshop_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.user_pool = cognito.UserPool(
            self,
            "UserPool",
            user_pool_name=f"crexi-{workshop_id}-users",
            self_sign_up_enabled=False,
            sign_in_aliases=cognito.SignInAliases(email=True, username=True),
            standard_attributes=cognito.StandardAttributes(
                email=cognito.StandardAttribute(required=True, mutable=True)
            ),
            removal_policy=RemovalPolicy.DESTROY,
        )

        self.app_client = self.user_pool.add_client(
            "WorkshopAppClient",
            user_pool_client_name=f"crexi-{workshop_id}-app",
            auth_flows=cognito.AuthFlow(user_password=True, user_srp=True, admin_user_password=True),
            generate_secret=False,
        )

        # A second app client + Hosted UI domain on the SAME pool, standing in for
        # "the legacy deal desk's own OAuth provider" (Checkpoint 4 / Legacy Portal
        # OAuth). Reusing dana/marcus's real identity here is deliberate: it's the
        # believable version of the scenario ("Marcus authorizes the agent using his
        # own CREXi identity"), and it avoids standing up a second, redundant user
        # pool + seeded users just for this one demo. This is a SEPARATE app client
        # (not WorkshopAppClient above) because it needs the OAuth authorization_code
        # grant + a client secret, neither of which the main app's client needs.
        #
        # Callback URLs are seeded with a placeholder because the real one (AgentCore
        # Identity's own callback, from `create-oauth2-credential-provider`) isn't
        # known until a participant creates that credential provider by hand in
        # Checkpoint 4 -- same two-phase problem as Gateway ARNs, solved the same way
        # this whole redesign solves it: the participant runs one more CLI command
        # (`aws cognito-idp update-user-pool-client`) themselves once they have the
        # real value, instead of a script patching it in after the fact.
        domain_prefix = f"crexi-{workshop_id}-legacy-oauth-{Stack.of(self).account}"[:63].lower()
        self.legacy_oauth_domain = self.user_pool.add_domain(
            "LegacyOAuthDomain",
            cognito_domain=cognito.CognitoDomainOptions(domain_prefix=domain_prefix),
        )

        self.legacy_oauth_client = self.user_pool.add_client(
            "LegacyOAuthAppClient",
            user_pool_client_name=f"crexi-{workshop_id}-legacy-oauth",
            generate_secret=True,
            o_auth=cognito.OAuthSettings(
                flows=cognito.OAuthFlows(authorization_code_grant=True),
                scopes=[cognito.OAuthScope.OPENID, cognito.OAuthScope.EMAIL],
                # Placeholder -- update this once the real AgentCore Identity
                # callback URL exists (see Checkpoint 4 in the walkthrough).
                callback_urls=["https://example.com/callback"],
            ),
            supported_identity_providers=[cognito.UserPoolClientIdentityProvider.COGNITO],
        )

        for group in ("investors", "brokers"):
            cognito.CfnUserPoolGroup(
                self,
                f"{group.capitalize()}Group",
                user_pool_id=self.user_pool.user_pool_id,
                group_name=group,
            )

        seed_users_fn = _lambda.Function(
            self,
            "SeedUsersFunction",
            function_name=f"crexi-{workshop_id}-seed-users",
            runtime=_lambda.Runtime.PYTHON_3_13,
            architecture=_lambda.Architecture.ARM_64,
            handler="seed_users_handler.on_event",
            code=_lambda.Code.from_asset("../services/seed"),
            timeout=Duration.minutes(2),
            log_retention=logs.RetentionDays.ONE_WEEK,
            environment={
                "USER_POOL_ID": self.user_pool.user_pool_id,
                "WORKSHOP_SECRET": os.environ.get("WORKSHOP_SECRET", "changeme-" + workshop_id),
            },
        )
        self.user_pool.grant(
            seed_users_fn,
            "cognito-idp:AdminCreateUser",
            "cognito-idp:AdminSetUserPassword",
            "cognito-idp:AdminAddUserToGroup",
        )

        provider = cr.Provider(self, "SeedUsersProvider", on_event_handler=seed_users_fn)
        CustomResource(
            self,
            "SeedUsersResource",
            service_token=provider.service_token,
            properties={"SeedVersion": "1"},
        )

        region = Stack.of(self).region
        self.discovery_url = (
            f"https://cognito-idp.{region}.amazonaws.com/{self.user_pool.user_pool_id}"
            "/.well-known/openid-configuration"
        )

        CfnOutput(self, "UserPoolId", value=self.user_pool.user_pool_id)
        CfnOutput(self, "AppClientId", value=self.app_client.user_pool_client_id)
        CfnOutput(self, "DiscoveryUrl", value=self.discovery_url)

        legacy_oauth_domain_url = f"https://{domain_prefix}.auth.{region}.amazoncognito.com"
        CfnOutput(self, "LegacyOAuthClientId", value=self.legacy_oauth_client.user_pool_client_id)
        CfnOutput(self, "LegacyOAuthIssuer", value=self.discovery_url.removesuffix("/.well-known/openid-configuration"))
        CfnOutput(self, "LegacyOAuthAuthorizationEndpoint", value=f"{legacy_oauth_domain_url}/oauth2/authorize")
        CfnOutput(self, "LegacyOAuthTokenEndpoint", value=f"{legacy_oauth_domain_url}/oauth2/token")
        CfnOutput(
            self,
            "LegacyOAuthClientSecretCommand",
            value=(
                f"aws cognito-idp describe-user-pool-client --user-pool-id {self.user_pool.user_pool_id} "
                f"--client-id {self.legacy_oauth_client.user_pool_client_id} "
                "--query 'UserPoolClient.ClientSecret' --output text"
            ),
        )

"""CDK custom-resource handler: creates the two workshop Cognito users
(dana/investors, marcus/brokers) with a deterministic password derived
from WORKSHOP_SECRET, so every account has the same login without a
secret being checked into git.
"""
import hashlib
import os

import boto3

cognito = boto3.client("cognito-idp")

USERS = [
    {"username": "dana", "email": "dana@crexi-workshop.local", "group": "investors"},
    {"username": "marcus", "email": "marcus@crexi-workshop.local", "group": "brokers"},
]


def _derived_password(username: str) -> str:
    secret = os.environ["WORKSHOP_SECRET"]
    digest = hashlib.sha256(f"{secret}:{username}".encode()).hexdigest()
    # Cognito requires upper/lower/digit/symbol; splice one of each in.
    return f"Wk-{digest[:20]}!9"


def on_event(event, context):
    request_type = event.get("RequestType", "Create")
    if request_type == "Delete":
        return {"PhysicalResourceId": "crexi-seed-users"}

    pool_id = os.environ["USER_POOL_ID"]

    for user in USERS:
        password = _derived_password(user["username"])
        try:
            cognito.admin_create_user(
                UserPoolId=pool_id,
                Username=user["username"],
                UserAttributes=[
                    {"Name": "email", "Value": user["email"]},
                    {"Name": "email_verified", "Value": "true"},
                ],
                MessageAction="SUPPRESS",
            )
        except cognito.exceptions.UsernameExistsException:
            pass

        cognito.admin_set_user_password(
            UserPoolId=pool_id, Username=user["username"], Password=password, Permanent=True
        )
        cognito.admin_add_user_to_group(
            UserPoolId=pool_id, Username=user["username"], GroupName=user["group"]
        )

    return {"PhysicalResourceId": "crexi-seed-users"}

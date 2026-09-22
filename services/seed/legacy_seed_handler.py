"""CDK custom-resource handler: seeds the legacy deal desk's own credential
and rent-roll/deferred-maintenance tables. Deliberately separate tables
from the listings/changelog data the MCPs read -- the legacy desk has
no API and no shared storage; Browser is the only way in.
"""
import hashlib
import os

import boto3

from listings_data import LEGACY_RECORDS, LEGACY_USERS

dynamodb = boto3.resource("dynamodb")


def _derived_password(username: str) -> str:
    secret = os.environ.get("WORKSHOP_SECRET", "changeme")
    digest = hashlib.sha256(f"legacy:{secret}:{username}".encode()).hexdigest()
    return f"Lg-{digest[:16]}"


def on_event(event, context):
    request_type = event.get("RequestType", "Create")
    if request_type == "Delete":
        return {"PhysicalResourceId": "crexi-seed-legacy"}

    creds_table = dynamodb.Table(os.environ["CREDS_TABLE"])
    records_table = dynamodb.Table(os.environ["RECORDS_TABLE"])

    for user in LEGACY_USERS:
        creds_table.put_item(Item={
            "username": user["username"],
            "password": _derived_password(user["username"]),
            "role": user["role"],
            "displayName": user["displayName"],
        })

    for listing_id, record in LEGACY_RECORDS.items():
        item = dict(record)
        item["listingId"] = listing_id
        records_table.put_item(Item=item)

    return {"PhysicalResourceId": "crexi-seed-legacy"}

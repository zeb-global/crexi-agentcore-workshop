"""CDK custom-resource handler: seeds DynamoDB listings + S3 comps/docs.
Idempotent -- overwrites to opening state on every Create/Update event, so
re-running `cdk deploy` (or `make seed`) always resets the scenario.
"""
import json
import os

import boto3

from listings_data import ALL_LISTINGS, MARKET_COMPS
from pdf_gen import build_om, build_t12

dynamodb = boto3.resource("dynamodb")
s3 = boto3.client("s3")


def on_event(event, context):
    request_type = event.get("RequestType", "Create")
    if request_type == "Delete":
        # DESTROY removal policy on the table/bucket handles cleanup.
        return {"PhysicalResourceId": "crexi-seed-data"}

    table = dynamodb.Table(os.environ["LISTINGS_TABLE"])
    bucket = os.environ["DOCS_BUCKET"]

    with table.batch_writer() as batch:
        for listing in ALL_LISTINGS:
            item = dict(listing)
            item["marketAssetType"] = f"{listing['market']}#{listing['assetType']}"
            item["version"] = 1
            batch.put_item(Item=item)

    s3.put_object(
        Bucket=bucket,
        Key="comps/columbus-multifamily-2025.json",
        Body=json.dumps(MARKET_COMPS, indent=2).encode("utf-8"),
        ContentType="application/json",
    )

    for listing in ALL_LISTINGS:
        if listing["market"] != "columbus-oh":
            continue  # only generate documents for properties in-scenario
        listing_id = listing["listingId"]
        t12 = build_t12(listing["name"], listing_id, listing["askingPrice"], listing["noi"])
        om = build_om(
            listing["name"], listing_id, listing["units"], listing["askingPrice"], listing["yearRenovated"]
        )
        s3.put_object(
            Bucket=bucket, Key=f"documents/{listing_id}/T12_2025.pdf",
            Body=t12, ContentType="application/pdf",
        )
        s3.put_object(
            Bucket=bucket, Key=f"documents/{listing_id}/OM.pdf",
            Body=om, ContentType="application/pdf",
        )

    return {"PhysicalResourceId": "crexi-seed-data"}

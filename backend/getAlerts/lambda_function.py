import os
import re
import json
import boto3
from decimal import Decimal
from boto3.dynamodb.conditions import Key

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(os.environ.get("TABLE_NAME", "FaceGuardAlertsByUser"))

USER_ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")


def respond(status, body):
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body, default=decimal_to_float),
    }


def decimal_to_float(obj):
    """DynamoDB returns numbers as Decimal, which JSON can't handle directly."""
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"Cannot serialize {type(obj)}")


def lambda_handler(event, context):
    headers = (event or {}).get("headers") or {}
    user_id = headers.get("x-user-id", "")
    if not USER_ID_PATTERN.match(user_id):
        return respond(400, {"error": "Missing or invalid user ID"})

    # Only this user's alerts are read.
    items = []
    response = table.query(KeyConditionExpression=Key("userId").eq(user_id))
    items.extend(response.get("Items", []))
    while "LastEvaluatedKey" in response:
        response = table.query(
            KeyConditionExpression=Key("userId").eq(user_id),
            ExclusiveStartKey=response["LastEvaluatedKey"],
        )
        items.extend(response.get("Items", []))

    # Newest and most suspicious first
    items.sort(key=lambda i: (i.get("scannedAt", ""), i.get("manipulationScore", 0)), reverse=True)

    return respond(200, {"count": len(items), "alerts": items})
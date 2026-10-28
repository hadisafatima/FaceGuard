import os
import json
import boto3
from decimal import Decimal

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(os.environ.get("TABLE_NAME", "FaceGuardAlerts"))


def decimal_to_float(obj):
    """DynamoDB returns numbers as Decimal, which JSON can't handle directly."""
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"Cannot serialize {type(obj)}")


def lambda_handler(event, context):
    items = []
    response = table.scan()
    items.extend(response.get("Items", []))
    while "LastEvaluatedKey" in response:
        response = table.scan(ExclusiveStartKey=response["LastEvaluatedKey"])
        items.extend(response.get("Items", []))

    items.sort(key=lambda i: (i.get("scannedAt", ""), i.get("manipulationScore", 0)), reverse=True)

    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({"count": len(items), "alerts": items}, default=decimal_to_float),
    }
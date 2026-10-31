import os
import re
import json
import boto3
from datetime import datetime, timezone
from botocore.exceptions import ClientError

dynamodb = boto3.resource("dynamodb")
sns = boto3.client("sns")
s3 = boto3.client("s3")

USERS_TABLE = os.environ.get("USERS_TABLE", "FaceGuardUsers")
SNS_TOPIC_ARN = os.environ["SNS_TOPIC_ARN"]
REF_BUCKET = os.environ["REF_BUCKET"]
MAX_REFS = int(os.environ.get("MAX_REFS", "5"))

users = dynamodb.Table(USERS_TABLE)

USER_ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def respond(status, body):
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def get_user_id(event):
    headers = event.get("headers") or {}
    user_id = headers.get("x-user-id", "")
    return user_id if USER_ID_PATTERN.match(user_id) else None


def count_refs(user_id):
    """Count the reference photos stored under this user's own folder."""
    total = 0
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=REF_BUCKET, Prefix=f"users/{user_id}/"):
        total += len(page.get("Contents", []))
    return total


def handle_me(user_id):
    item = users.get_item(Key={"userId": user_id}).get("Item", {})
    return respond(200, {
        "email": item.get("email"),
        "referenceCount": count_refs(user_id),
        "maxReferences": MAX_REFS,
    })


def handle_register(user_id, event):
    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return respond(400, {"error": "Invalid request"})

    email = str(body.get("email", "")).strip().lower()
    if len(email) > 254 or not EMAIL_PATTERN.match(email):
        return respond(400, {"error": "Enter a valid email address"})

    # Subscribe the address to the alerts topic. The filter means this address
    # only receives messages tagged with its own email, not other users' alerts.
    try:
        sns.subscribe(
            TopicArn=SNS_TOPIC_ARN,
            Protocol="email",
            Endpoint=email,
            Attributes={"FilterPolicy": json.dumps({"email": [email]})},
        )
    except ClientError as e:
        print(f"SNS subscribe failed for {email}: {e}")
        return respond(500, {"error": "Could not set up email alerts. Try again later."})

    now = datetime.now(timezone.utc).isoformat()
    existing = users.get_item(Key={"userId": user_id}).get("Item", {})
    users.put_item(Item={
        "userId": user_id,
        "email": email,
        "createdAt": existing.get("createdAt", now),
        "updatedAt": now,
    })

    return respond(200, {
        "email": email,
        "message": "Saved. Check your inbox for an email from AWS and click Confirm subscription.",
    })


def lambda_handler(event, context):
    user_id = get_user_id(event)
    if not user_id:
        return respond(400, {"error": "Missing or invalid user ID"})

    route = event.get("routeKey", "")
    if route == "GET /me":
        return handle_me(user_id)
    if route == "POST /register":
        return handle_register(user_id, event)
    return respond(404, {"error": "Not found"})
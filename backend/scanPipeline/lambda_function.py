import os
import re
import json
import boto3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal

lam = boto3.client("lambda")
sns = boto3.client("sns")
dynamodb = boto3.resource("dynamodb")

MATCH_FN = os.environ.get("MATCH_FUNCTION", "matchFaces")
SCORE_FN = os.environ.get("SCORE_FUNCTION", "scoreManipulation")
MANIP_THRESHOLD = float(os.environ.get("MANIP_THRESHOLD", "48"))
ALERTS_TABLE = os.environ.get("TABLE_NAME", "FaceGuardAlertsByUser")
USERS_TABLE = os.environ.get("USERS_TABLE", "FaceGuardUsers")
SNS_TOPIC_ARN = os.environ.get("SNS_TOPIC_ARN", "")
ALERT_ONLY_NEW = os.environ.get("ALERT_ONLY_NEW", "true").lower() == "true"

alerts_table = dynamodb.Table(ALERTS_TABLE)
users_table = dynamodb.Table(USERS_TABLE)

USER_ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")


class UserError(Exception):
    """A problem the user can fix. The message is shown in the extension."""


def call(function_name, payload=None):
    """Invoke another Lambda and return its parsed body."""
    resp = lam.invoke(
        FunctionName=function_name,
        InvocationType="RequestResponse",
        Payload=json.dumps(payload or {}).encode(),
    )
    outer = json.loads(resp["Payload"].read())
    if "errorMessage" in outer:
        raise RuntimeError(f"{function_name} failed: {outer['errorMessage']}")
    return json.loads(outer["body"])


def verdict_for(matched, manip_score):
    if not matched:
        return "No match"
    if manip_score is not None and manip_score >= MANIP_THRESHOLD:
        return "Possible deepfake"
    return "Unauthorized repost"


def to_dynamo(obj):
    """DynamoDB doesn't accept Python floats, so convert them to Decimal."""
    return json.loads(json.dumps(obj), parse_float=Decimal)


def get_request_user(event):
    """Return the caller's user ID, or None if there isn't one."""
    event = event or {}
    headers = event.get("headers") or {}
    user_id = headers.get("x-user-id") or event.get("userId") or ""
    if not user_id:
        return None
    if not USER_ID_PATTERN.match(user_id):
        raise UserError("Invalid user ID")
    return user_id


def list_user_ids():
    """All registered users (used by the scheduled scan)."""
    ids = []
    response = users_table.scan(ProjectionExpression="userId")
    ids.extend(i["userId"] for i in response.get("Items", []))
    while "LastEvaluatedKey" in response:
        response = users_table.scan(
            ProjectionExpression="userId",
            ExclusiveStartKey=response["LastEvaluatedKey"],
        )
        ids.extend(i["userId"] for i in response.get("Items", []))
    return ids


def get_user_email(user_id):
    item = users_table.get_item(Key={"userId": user_id}).get("Item", {})
    return item.get("email")


def find_new_alerts(user_id, flagged):
    """Return flagged images that this user doesn't have a saved alert for yet."""
    new = []
    for r in flagged:
        existing = alerts_table.get_item(Key={"userId": user_id, "imageId": r["image"]})
        if "Item" not in existing:
            new.append(r)
    return new


def save_alerts(user_id, flagged, scanned_at):
    """Store each flagged image as one row for this user (re-scans overwrite it)."""
    with alerts_table.batch_writer() as batch:
        for r in flagged:
            item = {
                "userId": user_id,
                "imageId": r["image"],
                "verdict": r["verdict"],
                "similarity": r["similarity"],
                "manipulationScore": r["manipulation_score"],
                "evidence": {
                    "ela_cv": r["ela_cv"],
                    "noise_mean": r["noise_mean"],
                    "tool_hits": r["tool_hits"] or [],
                },
                "scannedAt": scanned_at,
                "status": "new",
            }
            batch.put_item(Item=to_dynamo(item))


def send_alert(email, alerts, scanned_at):
    """Publish one summary email. The 'email' tag makes SNS deliver it only to that address."""
    lines = [
        f"FaceGuard found {len(alerts)} photo(s) matching your face that need your attention.",
        "",
    ]
    for i, a in enumerate(alerts, start=1):
        what = (
            "Appears edited or manipulated, a possible deepfake."
            if a["verdict"] == "Possible deepfake"
            else "Your photo appears at a source you did not post it to."
        )
        lines += [
            f"{i}. {a['image']}",
            f"   Verdict: {a['verdict']}",
            f"   {what}",
            f"   Face match: {a['similarity']}%",
            f"   Manipulation score: {a['manipulation_score']}/100",
            "",
        ]
    lines += [
        "Open the FaceGuard extension to review these and request removal or save evidence.",
        "Scores are likelihoods, not proof.",
        f"Scan time: {scanned_at}",
    ]
    sns.publish(
        TopicArn=SNS_TOPIC_ARN,
        Subject=f"FaceGuard: {len(alerts)} new alert(s)",
        Message="\n".join(lines),
        MessageAttributes={"email": {"DataType": "String", "StringValue": email}},
    )


def process_user(user_id, match_data, scores):
    """Turn match + manipulation results into verdicts, alerts and an email for one user."""
    if match_data.get("error"):
        raise UserError(match_data["error"])

    results = []
    for m in match_data["all_scores"]:
        image = m["image"]
        s = scores.get(image, {})
        manip = s.get("manipulation_score")
        f = s.get("features", {})
        results.append({
            "image": image,
            "similarity": m["similarity"],
            "manipulation_score": manip,
            "verdict": verdict_for(m["matched"], manip),
            "ela_cv": f.get("ela_cv"),
            "noise_mean": f.get("noise_mean"),
            "tool_hits": f.get("editing_tool_hits"),
        })

    flagged = [r for r in results if r["verdict"] != "No match"]
    scanned_at = datetime.now(timezone.utc).isoformat()

    # Decide what is new BEFORE saving, otherwise nothing would look new.
    to_alert = find_new_alerts(user_id, flagged) if ALERT_ONLY_NEW else flagged
    save_alerts(user_id, flagged, scanned_at)

    email = get_user_email(user_id)
    alerts_sent = 0
    alert_error = None
    if to_alert and not email:
        alert_error = "No email saved for this user, so alerts were saved but not emailed."
    elif to_alert and SNS_TOPIC_ARN:
        try:
            send_alert(email, to_alert, scanned_at)
            alerts_sent = len(to_alert)
        except Exception as e:
            alert_error = str(e)
            print(f"SNS publish failed for user {user_id}: {e}")

    return {
        "scanned": len(results),
        "flagged": len(flagged),
        "saved_to_table": len(flagged),
        "alerts_emailed": alerts_sent,
        "alert_error": alert_error,
        "results": [
            {k: r[k] for k in ("image", "similarity", "manipulation_score", "verdict")}
            for r in results
        ],
    }


def response(status, body):
    return {"statusCode": status, "body": json.dumps(body)}


def lambda_handler(event, context):
    event = event or {}
    is_api_call = "routeKey" in event  # requests from API Gateway carry a route

    try:
        user_id = get_request_user(event)

        # A person clicked "Scan now": scan only that person.
        if user_id:
            with ThreadPoolExecutor(max_workers=2) as pool:
                match_future = pool.submit(call, MATCH_FN, {"userId": user_id})
                score_future = pool.submit(call, SCORE_FN)
                match_data = match_future.result()
                score_data = score_future.result()
            scores = {r["image"]: r for r in score_data["results"]}
            return response(200, process_user(user_id, match_data, scores))

        # The web must never trigger a scan of everyone.
        if is_api_call:
            return response(400, {"error": "Missing user ID"})

        # Scheduled run: score the images once, then scan every registered user.
        score_data = call(SCORE_FN)
        scores = {r["image"]: r for r in score_data["results"]}
        summaries = []
        for uid in list_user_ids():
            try:
                match_data = call(MATCH_FN, {"userId": uid})
                summary = process_user(uid, match_data, scores)
                summary.pop("results", None)
                summaries.append({"userId": uid, **summary})
            except UserError as e:
                summaries.append({"userId": uid, "skipped": str(e)})
            except Exception as e:
                print(f"Scheduled scan failed for {uid}: {e}")
                summaries.append({"userId": uid, "error": "scan failed"})
        return response(200, {"users": len(summaries), "summaries": summaries})

    except UserError as e:
        return response(400, {"error": str(e)})
    except Exception as e:
        print(f"Scan failed: {e}")
        return response(500, {"error": "Scan failed. Please try again."})
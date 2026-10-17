import os
import json
import boto3
from datetime import datetime, timezone
from decimal import Decimal

lam = boto3.client("lambda")
sns = boto3.client("sns")
dynamodb = boto3.resource("dynamodb")

MATCH_FN = os.environ.get("MATCH_FUNCTION", "matchFaces")
SCORE_FN = os.environ.get("SCORE_FUNCTION", "scoreManipulation")
MANIP_THRESHOLD = float(os.environ.get("MANIP_THRESHOLD", "50"))
TABLE_NAME = os.environ.get("TABLE_NAME", "FaceGuardAlerts")
SNS_TOPIC_ARN = os.environ.get("SNS_TOPIC_ARN", "")
ALERT_ONLY_NEW = os.environ.get("ALERT_ONLY_NEW", "true").lower() == "true"

table = dynamodb.Table(TABLE_NAME)


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


def expected_verdict(filename):
    """TEST ONLY: guess the right answer from the filename prefix."""
    name = filename.lower()
    if name.startswith("real"):
        return "Unauthorized repost"
    if name.startswith("edited"):
        return "Possible deepfake"
    if name.startswith("other"):
        return "No match"
    return None


def to_dynamo(obj):
    """DynamoDB doesn't accept Python floats, so convert them to Decimal."""
    return json.loads(json.dumps(obj), parse_float=Decimal)


def find_new_alerts(flagged):
    """Return flagged images that are not already stored in the table."""
    new = []
    for r in flagged:
        existing = table.get_item(Key={"imageId": r["image"]})
        if "Item" not in existing:
            new.append(r)
    return new


def save_alerts(flagged, scanned_at):
    """Store every flagged image as one row (re-scans overwrite the same row)."""
    with table.batch_writer() as batch:
        for r in flagged:
            item = {
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


def send_alert(alerts, scanned_at):
    """Publish one summary email to the SNS topic."""
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
    )


def lambda_handler(event, context):
    match_data = call(MATCH_FN)
    score_data = call(SCORE_FN)

    scored = {r["image"]: r for r in score_data["results"]}

    results = []
    for m in match_data["all_scores"]:
        image = m["image"]
        s = scored.get(image, {})
        manip = s.get("manipulation_score")
        f = s.get("features", {})
        verdict = verdict_for(m["matched"], manip)
        expected = expected_verdict(image)
        results.append({
            "image": image,
            "similarity": m["similarity"],
            "manipulation_score": manip,
            "verdict": verdict,
            "expected": expected,
            "correct": (verdict == expected) if expected else None,
            "ela_cv": f.get("ela_cv"),
            "noise_mean": f.get("noise_mean"),
            "tool_hits": f.get("editing_tool_hits"),
        })

    flagged = [r for r in results if r["verdict"] != "No match"]
    checked = [r for r in results if r["correct"] is not None]

    scanned_at = datetime.now(timezone.utc).isoformat()

    # Decide who to email about BEFORE saving, otherwise nothing would look new.
    to_alert = find_new_alerts(flagged) if ALERT_ONLY_NEW else flagged
    save_alerts(flagged, scanned_at)

    alerts_sent = 0
    alert_error = None
    if to_alert and SNS_TOPIC_ARN:
        try:
            send_alert(to_alert, scanned_at)
            alerts_sent = len(to_alert)
        except Exception as e:
            alert_error = str(e)
            print(f"SNS publish failed: {e}")

    return {
        "statusCode": 200,
        "body": json.dumps({
            "scanned": len(results),
            "flagged": len(flagged),
            "saved_to_table": len(flagged),
            "alerts_emailed": alerts_sent,
            "alert_error": alert_error,
            "accuracy": f"{sum(r['correct'] for r in checked)}/{len(checked)}",
            "results": results,
        }),
    }
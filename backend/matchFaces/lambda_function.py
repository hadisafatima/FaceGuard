import os
import re
import json
import boto3
from concurrent.futures import ThreadPoolExecutor
from botocore.config import Config
from botocore.exceptions import ClientError

s3 = boto3.client("s3")
# "standard" retry mode automatically retries when Rekognition says "slow down"
rekognition = boto3.client(
    "rekognition",
    config=Config(retries={"max_attempts": 5, "mode": "standard"}),
)

REF_BUCKET = os.environ["REF_BUCKET"]
DATASET_BUCKET = os.environ["DATASET_BUCKET"]
THRESHOLD = float(os.environ.get("MATCH_THRESHOLD", "90"))

IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png")
USER_ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")


def list_images(bucket, prefix=""):
    """Return all image keys in a bucket (optionally only inside one folder)."""
    keys = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            if obj["Key"].lower().endswith(IMAGE_EXTENSIONS):
                keys.append(obj["Key"])
    return keys


def best_similarity(ref_keys, target_key):
    """Compare one target image to every reference photo, return the best score."""
    best = 0.0
    for ref_key in ref_keys:
        try:
            response = rekognition.compare_faces(
                SourceImage={"S3Object": {"Bucket": REF_BUCKET, "Name": ref_key}},
                TargetImage={"S3Object": {"Bucket": DATASET_BUCKET, "Name": target_key}},
                SimilarityThreshold=0,
            )
        except ClientError as e:
            # e.g. no face found in an image: skip this pair
            print(f"Skipped {ref_key} vs {target_key}: {e.response['Error']['Code']}")
            continue

        for match in response.get("FaceMatches", []):
            best = max(best, match["Similarity"])
    return round(best, 1)


def lambda_handler(event, context):
    user_id = (event or {}).get("userId", "")
    if not USER_ID_PATTERN.match(user_id):
        return {"statusCode": 400, "body": json.dumps({"error": "Missing or invalid user ID"})}

    # Only THIS user's reference photos are used.
    ref_keys = list_images(REF_BUCKET, f"users/{user_id}/")
    if not ref_keys:
        return {
            "statusCode": 200,
            "body": json.dumps({"error": "Upload at least one reference photo before scanning."}),
        }

    target_keys = list_images(DATASET_BUCKET)

    # Check several images at the same time to stay well inside the 30-second API limit.
    with ThreadPoolExecutor(max_workers=5) as pool:
        scores = list(pool.map(lambda key: best_similarity(ref_keys, key), target_keys))

    results = [
        {"image": key, "similarity": score, "matched": score >= THRESHOLD}
        for key, score in zip(target_keys, scores)
    ]
    results.sort(key=lambda r: r["similarity"], reverse=True)

    return {
        "statusCode": 200,
        "body": json.dumps({
            "threshold": THRESHOLD,
            "reference_count": len(ref_keys),
            "scanned": len(target_keys),
            "matches": [r for r in results if r["matched"]],
            "all_scores": results,
        }),
    }
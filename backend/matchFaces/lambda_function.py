import os
import json
import boto3
from botocore.exceptions import ClientError

s3 = boto3.client("s3")
rekognition = boto3.client("rekognition")

REF_BUCKET = os.environ["REF_BUCKET"]
DATASET_BUCKET = os.environ["DATASET_BUCKET"]
THRESHOLD = float(os.environ.get("MATCH_THRESHOLD", "90"))

IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png")


def list_images(bucket):
    """Return all image keys in a bucket."""
    keys = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket):
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
    ref_keys = list_images(REF_BUCKET)
    target_keys = list_images(DATASET_BUCKET)

    results = []
    for key in target_keys:
        score = best_similarity(ref_keys, key)
        results.append({"image": key, "similarity": score, "matched": score >= THRESHOLD})

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
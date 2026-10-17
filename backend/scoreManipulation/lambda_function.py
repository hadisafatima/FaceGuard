import os
import io
import json
import boto3
from PIL import Image, ImageChops, ImageFilter, ImageStat

s3 = boto3.client("s3")

DATASET_BUCKET = os.environ["DATASET_BUCKET"]
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png")

GRID = 8          # image is split into GRID x GRID blocks
MAX_SIDE = 768    # images are shrunk to this size for speed

# Over-smoothing detection (tuned on the demo dataset)
# noise_mean below ~6.4 starts to count; below ~4.0 is maxed out
NOISE_MEAN_HIGH, NOISE_MEAN_RANGE = 6.4, 2.4
# ela_cv below ~0.30 starts to count; below ~0.18 is maxed out
ELA_CV_HIGH, ELA_CV_RANGE = 0.30, 0.12
# score given when an editing/AI tool name is found in the metadata
META_TOOL_SCORE = 85

EDIT_KEYWORDS = [
    "photoshop", "gimp", "canva", "snapseed", "lightroom", "facetune",
    "picsart", "faceapp", "remini", "stable diffusion", "midjourney",
    "dall-e", "firefly",
]


def list_images(bucket):
    keys = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket):
        for obj in page.get("Contents", []):
            if obj["Key"].lower().endswith(IMAGE_EXTENSIONS):
                keys.append(obj["Key"])
    return keys


def load_image(bucket, key):
    data = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
    return Image.open(io.BytesIO(data))


def clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def block_means(gray_img, grid=GRID):
    """Average brightness of each block in a grid."""
    w, h = gray_img.size
    bw, bh = w // grid, h // grid
    means = []
    for gy in range(grid):
        for gx in range(grid):
            box = (gx * bw, gy * bh, (gx + 1) * bw, (gy + 1) * bh)
            means.append(ImageStat.Stat(gray_img.crop(box)).mean[0])
    return means


def cv(values):
    """Coefficient of variation: how uneven the values are."""
    m = sum(values) / len(values)
    if m == 0:
        return 0.0
    var = sum((v - m) ** 2 for v in values) / len(values)
    return (var ** 0.5) / m


def ela_features(img):
    """Error Level Analysis: recompress and see how evenly the image changes."""
    rgb = img.convert("RGB")
    rgb.thumbnail((MAX_SIDE, MAX_SIDE))
    buf = io.BytesIO()
    rgb.save(buf, "JPEG", quality=90)
    buf.seek(0)
    recompressed = Image.open(buf).convert("RGB")
    diff = ImageChops.difference(rgb, recompressed).convert("L")
    return {
        "ela_mean": round(ImageStat.Stat(diff).mean[0], 3),
        "ela_cv": round(cv(block_means(diff)), 3),
    }


def noise_features(img):
    """Noise consistency and overall noise level."""
    gray = img.convert("L")
    gray.thumbnail((MAX_SIDE, MAX_SIDE))
    blurred = gray.filter(ImageFilter.GaussianBlur(2))
    noise = ImageChops.difference(gray, blurred)
    return {
        "noise_cv": round(cv(block_means(noise)), 3),
        "noise_mean": round(ImageStat.Stat(noise).mean[0], 3),
    }


def metadata_features(img):
    """Look for editing-software or AI-tool traces in the image metadata."""
    exif = img.getexif()
    software = str(exif.get(305, "")) if exif else ""
    info_text = " ".join(str(v) for v in img.info.values() if isinstance(v, str))
    haystack = (software + " " + info_text).lower()
    hits = [k for k in EDIT_KEYWORDS if k in haystack]
    return {"has_exif": bool(exif), "editing_tool_hits": hits}


def combine(features):
    """Score over-smoothing: the strongest of three signals wins."""
    smooth = clamp((NOISE_MEAN_HIGH - features["noise_mean"]) / NOISE_MEAN_RANGE) * 100
    uniform = clamp((ELA_CV_HIGH - features["ela_cv"]) / ELA_CV_RANGE) * 100
    meta = META_TOOL_SCORE if features["editing_tool_hits"] else 0
    total = round(max(smooth, uniform, meta), 1)
    return total, {
        "noise_smoothness": round(smooth, 1),
        "ela_uniformity": round(uniform, 1),
        "metadata": meta,
    }


def score_image(bucket, key):
    img = load_image(bucket, key)
    features = {}
    features.update(ela_features(img))
    features.update(noise_features(img))
    features.update(metadata_features(img))
    total, parts = combine(features)
    return {"image": key, "manipulation_score": total, "parts": parts, "features": features}


def lambda_handler(event, context):
    # Score one image if a key is given, otherwise score the whole dataset.
    key = (event or {}).get("key")
    keys = [key] if key else list_images(DATASET_BUCKET)

    results = []
    for k in keys:
        try:
            results.append(score_image(DATASET_BUCKET, k))
        except Exception as e:
            print(f"Failed on {k}: {e}")
            results.append({"image": k, "error": str(e)})

    results.sort(key=lambda r: r.get("manipulation_score", -1), reverse=True)
    return {"statusCode": 200, "body": json.dumps({"results": results})}
# FaceGuard

A "Google Alerts for your face": a browser extension backed by AWS that scans
for photos matching your face and flags likely unauthorized reposts or
manipulated (deepfake) images.

## How it works
1. User uploads a private reference photo.
2. The backend compares it against a set of images (demo dataset).
3. Matches are scored for signs of manipulation.
4. The user gets an alert with a verdict and a link, and can request removal.

## AWS services
S3, Lambda, API Gateway, DynamoDB, Rekognition, SNS, EventBridge

## Project structure
- `extension/`  Chrome extension (popup UI)
- `backend/`    Lambda functions
- `dataset/`    Demo images and labels (consenting people only)
- `docs/`       Architecture and notes

## Status
Work in progress, built milestone by milestone.

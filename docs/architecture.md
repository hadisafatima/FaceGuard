# Architecture

Extension popup
      |
      v
API Gateway  -->  Lambda (scan pipeline)
                     |--> S3 (reference photo + dataset)
                     |--> Rekognition (face match)
                     |--> Lambda (manipulation score)
                     |--> DynamoDB (results)
                     '--> SNS (email alert)

EventBridge triggers the scan on a schedule.

## Decisions
- Scanning is simulated with a small labeled dataset for the demo.
- Manipulation detection: We are choosing Lambda-based image forensics (ELA + metadata + noise checks), outputting a 0-100 likelihood score. Chosen for free-tier compatibility. Limitation: not a guarantee against advanced AI edits.


## AWS resources
- Region: us-east-1
- Reference bucket: faceguard-reference-images
- Dataset bucket: faceguard-dataset-images


## M4 face-match scores (reference: ref_01.jpg)
| Image | Type | Similarity |
|---|---|---|
| real_01.jpeg | same person, real | 99.99 |
| edited_01.jpeg | same person, edited | 98.45 |
| others_01.jpeg | different person | 2.48 |


## M7 manipulation scores
| Image | Type | Score |
|---|---|---|
| real_01.jpeg | real | 46.1 |
| edited_01.jpeg | edited | 22.0 |
| others_01.jpeg | other | 29.7 |


- API: POST /scan, GET /alerts (HTTP API, us-east-1)

- Scan Scheduling: For scheduling we have chosen, EventBridge Scheduler, which runs daily by default & was set to 5 minutes only during testing to check whether scheduling was working or not, we chose 'once a day' (1000 calls per month) bcuz that's what a free tier account can easily manage (cost control).


- Chrome extensions don’t allow inline 'script' code, which is why the JavaScript is in its own file.

# Privacy and Security

## What FaceGuard stores
- Reference photos (the user's own face), in a private S3 bucket.
- A demo set of images to scan, in a second private S3 bucket.
- Alert records (image name, scores, verdict, timestamp) in DynamoDB.
- No passwords, no payment data, and no access keys in the code.

## Protections in place
- Both S3 buckets block all public access and use encryption at rest.
- The extension never receives AWS keys. Uploads use short-lived (5 minute),
  single-file upload tickets limited to JPG/PNG and 5 MB.
- Each Lambda has its own minimal IAM role (no wildcard actions).
- The API is rate-limited, and the number of reference photos is capped.
- Reference photos are only used to compare faces.
- Users can have their photos and alerts deleted on request.
- Test photos are of consenting people only, and the source repo is private.

## Known limitations (future work)
- The API has no user login. A production version would add Amazon Cognito so
  each user only sees and manages their own data.
- Detection is a likelihood score, not proof. A "possible deepfake" result is
  a prompt to look closer, not a verdict.
- Scanning is simulated with a demo dataset. Real web scanning would need
  legal review (consent, platform terms, data protection laws).
- Deletion on request is manual today. A signed-in "delete my data" button
  would automate it.
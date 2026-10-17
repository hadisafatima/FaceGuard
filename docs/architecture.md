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
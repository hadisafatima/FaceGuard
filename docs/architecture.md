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
- Manipulation detection approach: TBD (decided in M6).


## AWS resources
- Region: us-east-1
- Reference bucket: faceguard-reference-images
- Dataset bucket: faceguard-dataset-images


## M4 face-match scores (reference: ref_01.jpg)
| Image | Type | Similarity |
|---|---|---|
| real_01.jpeg | same person, real | 99.99 |
| edited_01.jpeg | same person, edited | 98.45 |
| other_01.jpg | different person | 2.48 |
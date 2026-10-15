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

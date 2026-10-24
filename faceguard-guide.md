# FaceGuard: How It Works and Why We Built It This Way

A plain-English guide for understanding the project, setting it up for the demo, and explaining it in your own words.

---

## 1. What FaceGuard does

FaceGuard is like "Google Alerts for your face".

1. You give it a few photos of yourself (the **reference photos**).
2. It looks through a pile of images (the **dataset**, which stands in for the internet).
3. If a photo shows your face, it checks two things:
   - Is this a photo of me somewhere I didn't post it? (**unauthorized repost**)
   - Does it look edited or AI-polished? (**possible manipulation / deepfake**)
4. If either is true, it saves an **alert**, sends you an **email**, and shows it in a **browser extension** where you can request removal in one click.

The goal: you find out about misuse yourself, quickly, instead of hearing about it from someone else after it has spread.

---

## 2. The two buckets (the most important idea)

| Bucket | What it holds | What it means |
|---|---|---|
| **Reference bucket** (`faceguard-reference-images`) | Photos of the user | "This is who I'm looking for" |
| **Dataset bucket** | Images to be checked | "Photos found online" |

Reference photos are never alerts. They are only the examples the system compares against. A photo only becomes an alert if it is in the **dataset** bucket and matches.

Why the internet is "simulated": a real internet crawler would raise legal, technical and privacy problems that don't fit a hackathon. A bucket of test images lets us show exactly the same logic safely. A real crawler would simply be another way of filling that bucket.

---

## 3. What happens during one scan (step by step)

```
You click "Scan now" in the extension
        |
        v
API Gateway receives POST /scan
        |
        v
scanPipeline Lambda (the manager)
   |-- 1. calls matchFaces Lambda
   |       - lists every reference photo and every dataset image
   |       - asks Rekognition how similar each image is to each reference photo
   |       - keeps the HIGHEST score per image (90 or more = "this is you")
   |
   |-- 2. calls scoreManipulation Lambda
   |       - checks every image for signs of editing, gives a 0 to 100 score
   |
   |-- 3. decides a verdict for each image
   |       - not you                          -> "No match" (ignored)
   |       - you, score below 48              -> "Unauthorized repost"
   |       - you, score 48 or above           -> "Possible deepfake"
   |
   |-- 4. saves flagged images in DynamoDB (one row per image)
   |
   '-- 5. sends ONE email for images that are NEW alerts (not in the table yet)
        |
        v
The extension reloads GET /alerts and shows the list
```

Two things worth understanding:

- **An alert row is a record of a finding.** The same image scanned twice updates the same row (the row is keyed by the image name), so you never get duplicates.
- **Emails only go out for new findings.** The pipeline checks whether the image is already in the table before saving. If it is, it's old news, so no email. That's why deleting a row makes the next scan treat the image as new and email again.

---

## 4. Getting ready to demo: what to delete and restore

Your current state: **2 images in the reference bucket, 11 in the dataset bucket.** That's the clean, full state. The demo works best if two images are held back and added live, so the audience sees a new finding appear.

### Pick the two live images

| Image | Why this one |
|---|---|
| `real_01.jpeg` | Real photo, manipulation score 0, a clean "unauthorized repost" |
| `edited_04.jpeg` | Edited photo, score 100, a clear "possible deepfake" |

### Before the demo: remove them

Do all of these. Missing one breaks the demo.

| Where | What to delete | Why |
|---|---|---|
| **Your PC** | Nothing. Copy both files to a `demo-live` folder on the Desktop first | You need them to upload live |
| **S3, dataset bucket** | `real_01.jpeg` and `edited_04.jpeg` | So they aren't found until you add them on stage |
| **DynamoDB, `FaceGuardAlerts` table** | The row where `imageId` is `real_01.jpeg` and the row where `imageId` is `edited_04.jpeg` | If a row exists, the image is not "new", so no email is sent |

Leave **everything else alone**:

- Do **not** delete anything from the **reference** bucket.
- Do **not** delete the other DynamoDB rows. After you remove those two, 5 rows should remain (`real_02`, `real_03`, `edited_01`, `edited_02`, `edited_03`), which is the "existing alerts" the demo starts with.
- Do **not** delete the `others_` images. They never create rows anyway, because they don't match.

How to delete a DynamoDB row: **DynamoDB -> Tables -> FaceGuardAlerts -> Explore table items**, tick the row's checkbox, then **Actions -> Delete items**.

### Also check before the demo

- `ALERT_ONLY_NEW` on the `scanPipeline` Lambda is `true`.
- The EventBridge schedule is **Disabled** during the demo, so it can't grab your new findings before you click Scan now. Re-enable it as `1 days` afterwards.
- Click **Scan now** once about 5 minutes before you start (a "warm-up" so the first live scan isn't slow). It should show 5 flagged.

### During the demo

1. Drag `real_01.jpeg` and `edited_04.jpeg` into the dataset bucket (this is the "internet" posting them).
2. Click **Scan now**. Two new alerts appear and one email arrives.

### After the demo: back to the full state

1. Upload both images back into the dataset bucket (11 images again).
2. Click **Scan now**. The table goes back to 7 rows.
3. Set the EventBridge schedule back to `1 days` (or leave it disabled).

---

## 5. Services we used

### AWS services

| Service | What we used it for | Why this one |
|---|---|---|
| **S3** | Two private buckets: reference photos and dataset images | Cheap, simple, private file storage |
| **Rekognition** | Comparing faces (`CompareFaces`) | A ready-made face-matching service, so we don't build a model |
| **Lambda** | Five small functions: `matchFaces`, `scoreManipulation`, `scanPipeline`, `getAlerts`, `getUploadUrl` | Code that runs only when called, with no server to manage |
| **Lambda layer** | Packaging the Pillow image library | Lambda doesn't include Pillow, and a layer adds it |
| **API Gateway (HTTP API)** | The public address the extension calls: `POST /scan`, `GET /alerts`, `POST /upload-url` | The front door that connects the extension to the Lambdas |
| **DynamoDB** | The `FaceGuardAlerts` table | Simple key-value storage, and the always-free allowance is enough |
| **SNS** | Email alerts | Sends notifications without running a mail server |
| **EventBridge Scheduler** | Running the scan on a schedule | Makes the monitor automatic |
| **IAM** | Giving each Lambda only the permissions it needs | Security: least privilege |
| **CloudWatch Logs** | Reading Lambda logs when something failed | Created automatically, and it's how we found the errors |
| **CloudShell** | Building the Pillow layer and running test commands | A terminal in the browser with no setup |

### Outside AWS

| Tool | What we used it for |
|---|---|
| **Chrome extension (Manifest V3)** | The user interface: alerts list, scan button, photo upload, removal button |
| **Python + Pillow** | The image-forensics checks inside `scoreManipulation` |
| **GitHub** | Version control and backup (private repo) |
| **Gmail compose link** | Opening the pre-filled takedown email |

---

## 6. The approach: how we built it and why

### Start from the problem, then split it into small, testable pieces

The problem is "tell me when my face is misused". We cut it into four questions:

1. Whose face is this? (face matching)
2. Has it been edited? (manipulation detection)
3. Where do results go? (storage and alerts)
4. How does the user see and act on it? (the extension)

Each question became its own piece, and we built and tested one at a time (that's what the milestones were). If something broke, we knew which piece to look at.

### Use managed services instead of building from scratch

For face matching we didn't train a model. We used Rekognition, which is already trained and accurate. This is a normal cloud decision: don't build what you can rent. It saved time and gave better accuracy than anything we could train.

### Serverless, because it fits the problem

Scans happen occasionally, not constantly. With Lambda, API Gateway and DynamoDB, nothing runs (or costs money) while nobody is scanning. That also suits the free tier, which was a requirement.

### Three Lambdas for the scan, not one big one

`matchFaces` answers "is it you?", `scoreManipulation` answers "is it edited?", and `scanPipeline` combines the answers. Splitting them means each can be tested alone (we did exactly that), each has its own small permission set, and one can be improved without touching the others. When the manipulation scoring needed a rewrite, the face matching was unaffected.

### The extension never holds AWS keys

The browser can't be trusted with secrets. So the extension only talks to API Gateway, and for uploads it asks a Lambda for a short-lived upload ticket (a presigned URL). The ticket allows one file, JPG or PNG only, up to 5 MB, for 5 minutes. The photo then goes straight into the private bucket.

### Cost control was part of the design

Each scan makes (number of images x number of reference photos) Rekognition calls. We kept costs inside the free tier with several measures:

- The schedule runs daily, not every few minutes.
- Reference photos are capped (`MAX_REFS`).
- API Gateway throttling limits how fast the API can be called.
- The EventBridge retry policy is off, so a failed run can't repeat all day.

### Only alert on what's new

Emailing the same finding on every scan would train the user to ignore the emails. So the pipeline checks the table first and emails only for images it hasn't seen.

---

## 7. How the two detections actually work

### Face matching (Rekognition)

Rekognition turns each face into a set of measurements and returns a **similarity percentage**. We compare each dataset image to every reference photo and keep the best score. **90% or more** counts as "this is you". Having several reference photos helps, because it covers different angles and lighting. In our tests, photos of the user scored 93.9% to 100%, and other people scored under 15%.

### Manipulation score (our own forensics, 0 to 100)

Rekognition can't tell whether a photo was edited, so we wrote this part ourselves with simple image analysis. We measure three things:

1. **Noise level.** Every real photo has fine grain from the camera. Heavy AI polishing and beauty filters smooth that grain away. A very low noise level is a sign of smoothing.
2. **Compression evenness (Error Level Analysis).** We re-save the image as a JPEG at a fixed quality and see how much each area changes. Natural photos change unevenly. A photo that was filtered and re-saved often changes very evenly.
3. **Editing-app names in the metadata.** If the file records that it was made by Photoshop, Snapseed, FaceApp and so on, that's a strong hint.

The strongest of those three signals becomes the score. A score of 48 or higher counts as "possible manipulation".

### Why we chose this instead of a deepfake AI model

We looked at three options. A downloaded deepfake model is heavy (often over a gigabyte once packaged), and we could end up paying to store and run it, which didn't fit a free-trial budget. Using Rekognition's face attributes as hints isn't real detection. So we picked simple image forensics: free, small, explainable and testable.

---

## 8. What went wrong along the way (and what it taught us)

These are real, and they are the most convincing things to talk about.

| What happened | What we learned |
|---|---|
| Our first scoring assumed edits make an image **more** uneven. The test data showed the opposite: the polished and filtered photos were **smoother**, and some real photos scored higher than edited ones (accuracy 5/7, then 9/11). | Don't trust your first assumption. We printed the raw measurements, looked at the pattern, and redesigned the score around over-smoothing. After that it reached 11/11. |
| The test accuracy ignored the "others" images. | The helper looked for names starting with `other_`, but the files were named `others_`. A naming mismatch, not a logic bug. Check the small things first. |
| `AccessDenied` errors in CloudWatch for the upload Lambda. | IAM denies everything by default. Each Lambda needs exactly the permissions it uses, and the logs tell you which one is missing. |
| Browser CORS error when uploading to S3. | The browser blocks requests to another site unless that site says it's allowed. The bucket needed a CORS rule. |
| Opening `/scan` in the browser said "Not Found". | The address bar sends GET requests, but `/scan` accepts only POST. |
| "Mail app didn't open" on Request removal. | `mailto:` links need a default mail app. A Gmail compose link works in the browser instead. |

---

## 9. Honest limitations (say these yourself, before anyone asks)

- **The score is a likelihood, not proof.** We tuned it on a small dataset of photos, so it fits our test images. A stronger or different kind of edit could slip through, and an unusual real photo could be flagged.
- **It finds smoothing, not true deepfakes.** Our "edited" photos were AI-polished and filtered. A face swap or fully AI-generated face needs a trained detection model.
- **The internet is simulated.** A real version would need a crawler and a legal review.
- **No user login.** Anyone with the API address could call it. A real version would add Amazon Cognito so each person only sees their own data.
- **Deleting data is manual** today. A real version would offer a signed-in "delete my data" button.

### What we would do next

1. Add sign-in (Amazon Cognito).
2. Replace the forensic score with a trained deepfake-detection model, for example hosted on SageMaker.
3. Connect real sources (search results and social platforms, through their approved APIs).
4. Link each alert to the correct takedown form of the site it was found on.

---

## 10. Check your own understanding

If you can answer these in your own words, you understand the project.

1. **Why are there two buckets?** One says who to look for, the other holds what to look through.
2. **Why does an uploaded reference photo never create an alert?** Alerts only come from the dataset bucket. References are only comparison examples.
3. **Why was no email sent when you scanned twice?** The images were already in the table, so they weren't new.
4. **Why take the highest score across the reference photos?** If any one of them recognizes the face, it's a match.
5. **Why isn't the extension given AWS keys?** Anything inside a browser can be read, so the extension only gets short-lived, single-purpose tickets.
6. **Why did we write our own detection rather than use Rekognition for it?** Rekognition recognizes faces, but it can't tell if an image was edited.
7. **What would break if you forgot to delete the DynamoDB rows before the demo?** The live images wouldn't count as new, so no email would be sent.
8. **What is the weakest part of the project, and why?** The manipulation score: it's tuned to a small dataset and catches smoothing, not every kind of deepfake.

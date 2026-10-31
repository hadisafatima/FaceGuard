# FaceGuard: How It Works and Why We Built It This Way

A plain-English guide for understanding the project, setting it up for the demo, and explaining it in your own words. This version covers the **multi-user** design (every person has their own photos, alerts and email).

---

## 1. What FaceGuard does

FaceGuard is like "Google Alerts for your face".

1. A person gives it a few photos of themselves (the **reference photos**) and their email address.
2. It looks through a pile of images (the **dataset**, which stands in for the internet).
3. If a photo shows that person's face, it checks two things:
   - Is this a photo of me somewhere I didn't post it? (**unauthorized repost**)
   - Does it look edited or AI-polished? (**possible manipulation / deepfake**)
4. If either is true, it saves an **alert**, sends that person an **email**, and shows the alert in a **browser extension** (or web dashboard) where they can request removal in one click.

The goal: people find out about misuse themselves, quickly, instead of hearing about it from someone else after it has spread.

---

## 2. The big picture

```
 Chrome extension  ----\
                         >---> API Gateway ---> Lambda functions ---> S3, DynamoDB, Rekognition, SNS
 Web dashboard (Amplify)/            (front door)     (the logic)        (storage, face matching, email)

 EventBridge Scheduler ----------------------> scanPipeline (daily scan for every registered user)
```

- The **extension** and the **web dashboard** use the same code (`popup.js`). Both talk to the same API.
- **API Gateway** is the front door. It receives requests and passes each one to the right Lambda.
- **Lambda** functions hold the logic. Nothing runs (or costs money) while nobody is using the system.
- **S3** stores photos, **DynamoDB** stores users and alerts, **Rekognition** matches faces, **SNS** sends emails.

---

## 3. Who is who: users, photos, alerts and emails

The first version of FaceGuard was single-user: one set of reference photos, one table of alerts, one email. If two people had used it, they would have seen each other's alerts. Making it multi-user was the main change in the later milestones.

### How the system tells people apart

We chose a simple approach for a prototype: **no accounts, just an anonymous ID.**

- The first time FaceGuard opens in a browser, it creates a random 32-character ID and stores it in that browser.
- Every request to AWS carries that ID (in a header called `x-user-id`).
- The backend uses the ID to keep each person's data separate.

An ID is practically impossible to guess, so it works like a private key. But it is **not real login**: if someone clears their browser data, they lose access, and anyone who got hold of the ID could act as that person. A real product would use Amazon Cognito for sign-in. That is our stated "future work".

### Where each person's data lives

| Data | Where it is stored | How it is kept separate |
|---|---|---|
| Reference photos | Reference bucket, in a folder `users/<ID>/` | Each person's photos are in their own folder |
| Email address | `FaceGuardUsers` table (one row per user) | Row key is the user ID |
| Alerts | `FaceGuardAlertsByUser` table | Each row has the user ID plus the image name, so a user only reads their own rows |
| Email delivery | SNS topic `faceguard-alerts` | Each address has its own filter (explained below) |

### How emails reach the right person

SNS is like a notice board with a mailing list:

1. When a person saves their email in the extension, the backend adds that address to the mailing list. AWS emails them a confirmation link, and nothing is delivered until they click it. That proves they own the address.
2. The subscription carries a **filter**: "only deliver messages tagged with my email address".
3. When a scan finds something, the scan code posts the alert message **tagged with that person's email**.
4. SNS delivers it only to the address that matches the tag.

So the scan code never sends email directly, and one person's alerts can never reach another person's inbox.

---

## 4. The two kinds of images (the most important idea)

| | What it holds | What it means |
|---|---|---|
| **Reference photos** (reference bucket, `users/<ID>/`) | Photos of the user | "This is who I'm looking for" |
| **Dataset images** (dataset bucket) | Images to be checked | "Photos found online" |

Reference photos are never alerts. They are only the examples the system compares against. An image only becomes an alert if it is in the **dataset** bucket and matches that user's reference photos.

The dataset is shared by everyone (it stands in for the internet), but **each scan only compares it against the caller's own reference photos**.

Why the internet is "simulated": see section 10.

---

## 5. What happens during one scan (step by step)

```
A person clicks "Scan now" in the extension
        |
        v
API Gateway receives POST /scan (with the person's ID)
        |
        v
scanPipeline Lambda (the manager)
   |
   |-- 1. In parallel:
   |       a) matchFaces Lambda
   |            - lists THIS person's reference photos (users/<ID>/)
   |            - lists every dataset image
   |            - asks Rekognition how similar each image is to each of their photos
   |            - keeps the HIGHEST score per image (90 or more = "this is you")
   |            - if the person has no reference photos: stops with a clear message
   |       b) scoreManipulation Lambda
   |            - checks every image for signs of editing, 0 to 100
   |
   |-- 2. Decides a verdict for each image
   |       - not you                       -> "No match" (ignored)
   |       - you, score below 48           -> "Unauthorized repost"
   |       - you, score 48 or above        -> "Possible deepfake"
   |
   |-- 3. Finds which flagged images are NEW for this person
   |       (no row yet in their alerts)
   |
   |-- 4. Saves all flagged images in FaceGuardAlertsByUser (one row per user + image)
   |
   '-- 5. If there are new alerts and the person has an email saved:
           sends ONE email, tagged with their address
        |
        v
The extension reloads GET /alerts and shows only that person's alerts
```

Things worth understanding:

- **An alert row is a record of a finding.** The same image scanned twice updates the same row, so there are never duplicates.
- **Emails only go out for new findings.** The pipeline checks whether the image already has a row before saving. If it does, it's old news, so no email. That is why deleting a row makes the next scan treat the image as new.
- **The scheduled scan** (EventBridge, once a day) has no person attached, so it loops over every registered user who has reference photos and does the same steps for each. A web request can never trigger a scan of everyone.

---

## 6. All the pieces: endpoints and code map

### API endpoints (API Gateway)

| Method | Path | Lambda | What it does |
|---|---|---|---|
| GET | `/alerts` | `getAlerts` | Returns this user's saved alerts |
| POST | `/scan` | `scanPipeline` | Runs a scan for this user |
| POST | `/upload-url` | `getUploadUrl` | Gives a short-lived ticket to upload one reference photo to this user's folder |
| POST | `/register` | `manageUser` | Saves the user's email and subscribes it to alerts |
| GET | `/me` | `manageUser` | Returns the user's saved email and how many reference photos they have |

The extension never names a Lambda. It calls a path, and API Gateway decides which Lambda handles it. The routes and their Lambdas are set up in the console under **API Gateway -> Routes / Integrations**.

### The Lambda functions

| Lambda | Its one job |
|---|---|
| `matchFaces` | Compares a user's reference photos against each dataset image using Rekognition and returns a similarity score per image |
| `scoreManipulation` | Gives each image a 0 to 100 "looks edited" score using image forensics (Python + Pillow) |
| `scanPipeline` | The manager: calls the two above, decides verdicts, saves alerts, sends the email |
| `getAlerts` | Reads one user's alerts from DynamoDB |
| `getUploadUrl` | Creates the upload ticket, checks the file type and the per-user photo limit |
| `manageUser` | Registers an email (with its SNS filter) and reports a user's profile |

### The extension / dashboard files

| File | Job |
|---|---|
| `manifest.json` | Tells Chrome what the extension is, its icon, and which addresses it may call |
| `popup.html` | The layout: alerts list, Scan button, email box, reference photo upload, ID line |
| `popup.css` | The look |
| `popup.js` | The behavior: creates the user ID, calls the API, draws the alerts, builds the takedown message, uploads photos |
| `index.html`, `web.css`, `install.html` | The web dashboard version and the extension install page (hosted on Amplify) |

---

## 7. Services we used

### AWS services

| Service | What we used it for | Why this one |
|---|---|---|
| **S3** | Two private buckets: reference photos (per-user folders) and dataset images | Cheap, simple, private file storage |
| **Rekognition** | Comparing faces (`CompareFaces`) | A ready-made face-matching service, so we don't build a model |
| **Lambda** | Six small functions (see above) | Code that runs only when called, with no server to manage |
| **Lambda layer** | Packaging the Pillow image library | Lambda doesn't include Pillow, and a layer adds it |
| **API Gateway (HTTP API)** | The public address with five routes | The front door that connects the extension to the Lambdas |
| **DynamoDB** | Two tables: `FaceGuardUsers` and `FaceGuardAlertsByUser` | Simple key-value storage, and the always-free allowance is enough |
| **SNS** | Email alerts, with a per-address filter | Sends notifications without running a mail server |
| **EventBridge Scheduler** | Running the scan once a day | Makes the monitor automatic |
| **Amplify Hosting** | The web dashboard and the extension download page | Easy, free-tier hosting for a small static site |
| **IAM** | Giving each Lambda only the permissions it needs | Security: least privilege |
| **CloudWatch Logs** | Reading Lambda logs when something failed | Created automatically, and it's how we found the errors |
| **CloudShell** | Building the Pillow layer and running test commands | A terminal in the browser with no setup |

### Outside AWS

| Tool | What we used it for |
|---|---|
| **Chrome extension (Manifest V3)** | The user interface for end users |
| **Python + Pillow** | The image-forensics checks inside `scoreManipulation` |
| **GitHub** | Version control and backup (private repo) |
| **Gmail compose link** | Opening the pre-filled takedown email |

---

## 8. How the two detections actually work

### Face matching (Rekognition)

Rekognition turns each face into a set of measurements and returns a **similarity percentage**. We compare each dataset image to every one of the user's reference photos and keep the best score. **90% or more** counts as "this is you".

The direction matters: the reference photo is the **source** ("this is the face I'm looking for") and the dataset image is the **target** ("look for that face in here"). That is why a group photo with many faces still works: Rekognition looks for the reference face among all faces in the image.

Having several reference photos helps, because it covers different angles and lighting. In our single-user tests, photos of the user scored 93.9% to 100%, and other people scored under 15%.

### Manipulation score (our own forensics, 0 to 100)

Rekognition can't tell whether a photo was edited, so we wrote this part ourselves with simple image analysis. We measure three things, and the **strongest** one becomes the score:

1. **Noise level.** Every real photo has fine grain from the camera. Heavy AI polishing and beauty filters smooth that grain away. A very low noise level is a sign of smoothing.
2. **Compression evenness (Error Level Analysis).** We re-save the image as a JPEG at a fixed quality and see how much each part changes. Natural photos change unevenly. A photo that was filtered and re-saved often changes very evenly.
3. **Editing-app names in the metadata.** If the file records that it was made by Photoshop, Snapseed, FaceApp and so on, that's a strong hint.

A score of **48 or higher** counts as "possible manipulation".

This score does not depend on who the user is, so `scoreManipulation` runs once per scan and its results are shared.

### Why we chose this instead of a deepfake AI model

We looked at three options. A downloaded deepfake model is heavy (often over a gigabyte once packaged), and we could end up paying to store and run it, which didn't fit a free-trial budget. Using Rekognition's face attributes as hints isn't real detection. So we picked simple image forensics: free, small, explainable and testable.

---

## 9. The approach: how we built it and why

### Start from the problem, then split it into small, testable pieces

The problem is "tell me when my face is misused". We cut it into four questions:

1. Whose face is this? (face matching)
2. Has it been edited? (manipulation detection)
3. Where do results go? (storage and alerts)
4. How does the user see and act on it? (the extension)

Each question became its own piece, and we built and tested one milestone at a time. If something broke, we knew which piece to look at.

### Use managed services instead of building from scratch

For face matching we didn't train a model. We used Rekognition, which is already trained and accurate. This is a normal cloud decision: don't build what you can rent.

### Serverless, because it fits the problem

Scans happen occasionally, not constantly. With Lambda, API Gateway and DynamoDB, nothing runs (or costs money) while nobody is scanning. That also suits the free tier, which was a requirement.

### Separate Lambdas, not one big one

`matchFaces` answers "is it you?", `scoreManipulation` answers "is it edited?", and `scanPipeline` combines the answers. Splitting them means each can be tested alone, each has its own small permission set, and one can be improved without touching the others. When the manipulation scoring needed a rewrite, the face matching was unaffected.

### The extension never holds AWS keys

The browser can't be trusted with secrets. So the extension only talks to API Gateway, and for uploads it asks a Lambda for a short-lived upload ticket (a presigned URL). The ticket allows one file, JPG or PNG only, up to 5 MB, for 5 minutes, into that user's own folder. The photo then goes straight into the private bucket.

### Multi-user without accounts

We needed each person's data to be separate but wanted to keep the prototype simple. An anonymous random ID, a per-user folder, a per-user table key and a per-address email filter achieved that without building a login system. We were upfront that real accounts (Cognito) are the production answer.

### Cost control was part of the design

Each scan makes (number of images x that user's number of reference photos) Rekognition calls. We kept costs inside the free tier with several measures:

- The schedule runs daily, not every few minutes.
- Reference photos are capped per user (`MAX_REFS`).
- API Gateway throttling limits how fast the API can be called.
- The EventBridge retry policy is off, so a failed run can't repeat all day.
- Images are checked several at a time, so a scan stays well inside the API's 30-second limit.

### Only alert on what's new

Emailing the same finding on every scan would train the user to ignore the emails. So the pipeline checks the table first and emails only for images that user hasn't been alerted about.

---

## 10. Why we didn't scrape the real internet

We simulated the source of the images instead of scraping the real internet, for four reasons:

1. **Cost.** The project had to stay within the AWS free trial. A real crawl needs paid search services and many Rekognition checks, which would use up the free allowance within hours.
2. **Privacy and law.** Finding one person's face means examining thousands of strangers' faces, which is sensitive data that many privacy laws restrict. Companies that scraped public photos for face recognition have been fined by regulators.
3. **Reliability.** Most big platforms forbid scraping in their terms, block bots, and hide content behind logins, so a scraper would break often.
4. **Proof.** With our own consented test images we know which are real, edited or unrelated, so we can measure accuracy honestly (11 out of 11 on our original test set). On the live internet we couldn't know the right answers.

Everything after the images arrive is built for real, so a crawler or a reverse-image-search service could later feed the same bucket without changing anything else.

---

## 11. How FaceGuard compares with existing tools

| Tool (as far as we know) | What it does | What it doesn't do |
|---|---|---|
| **PimEyes** | Searches the web for where a face appears and can alert subscribers; paid, entry plans around $30 a month when we checked | Doesn't tell you whether a photo was edited; closed, paid service |
| **Deepfake detectors** (e.g. Sensity, Reality Defender, Hive) | Judge whether an image or video you give them is fake, mostly for companies | Don't search for where your face appears |
| **StopNCII.org / Take It Down** | Free services to block specific intimate images on partner platforms | Only protect images you already know about |
| **Google Alerts** | Notifies you when words appear in new pages | Works on text, not faces |

**How FaceGuard is different:**

1. It joins the steps together: find -> check for edits -> alert -> draft the takedown request.
2. It checks for manipulation, not just matches.
3. The score is explainable (three visible measurements), not a black box.
4. It is open, serverless and nearly free.
5. Photos stay in the user's own private storage rather than a third party's index.

**What they do better:** real crawling at huge scale and trained detection models. FaceGuard is a prototype of an integrated monitor, not a competitor in coverage.

---

## 12. Getting ready to demo

### The demo idea

Two images are held back and added live, so the audience sees a brand-new finding appear. Then you show a second user to prove people are kept separate.

| Image | Why this one |
|---|---|
| `real_01.jpeg` | Real photo, manipulation score 0, a clean "unauthorized repost" |
| `edited_04.jpeg` | Edited photo, score 100, a clear "possible deepfake" |

### Before the demo: reset

Do all of these. Missing one breaks the demo.

| Where | What to do | Why |
|---|---|---|
| **Your PC** | Copy both images to a `demo-live` folder on the Desktop | You need them to upload live |
| **S3, dataset bucket** | Delete `real_01.jpeg` and `edited_04.jpeg` | So they aren't found until you add them on stage |
| **DynamoDB, `FaceGuardAlertsByUser`** | Delete the rows for `real_01.jpeg` and `edited_04.jpeg` (each row has your `userId` plus the `imageId`) | If a row exists, the image is not "new", so no email is sent |

Leave everything else alone:

- Do **not** delete anything in the reference bucket (your photos in `users/<your ID>/`).
- Do **not** delete your other alert rows. They are the "existing alerts" the demo starts with. How many there are depends on which reference photos you uploaded (about 5 in our tests).
- Do **not** delete the `others_` images. They never create rows, because they don't match.

How to delete a row: **DynamoDB -> Tables -> FaceGuardAlertsByUser -> Explore table items**, tick the row, then **Actions -> Delete items**.

### Also check before the demo

- Your email is saved and the SNS subscription shows **Confirmed**.
- `ALERT_ONLY_NEW` on `scanPipeline` is `true`.
- The EventBridge schedule is **Disabled** during the demo, so it can't grab your new findings before you click Scan now. Re-enable it as `1 days` afterwards.
- Click **Scan now** once about 5 minutes before you start, so the first live scan isn't slow.
- You are in region **US East (N. Virginia)** in the console. Resources in other regions are invisible.
- Gmail is open and signed in; phone on silent.

### During the demo

1. Show the popup with your existing alerts.
2. Drag `real_01.jpeg` and `edited_04.jpeg` into the dataset bucket (this is the "internet" posting them).
3. Click **Scan now**. Two new alerts appear and one email arrives.
4. Show the email, then click **Request removal** to open the pre-filled draft.
5. **Second user moment (about 30 seconds):** open the second Chrome profile. It shows a different ID, none of your alerts, and its own email. Explain that each person's photos, alerts and emails are kept separate.

### After the demo: back to the full state

1. Upload both images back into the dataset bucket.
2. Click **Scan now** to restore the rows.
3. Set the EventBridge schedule back to `1 days` (or leave it disabled).
4. If you shared the web dashboard link, delete the Amplify app when you are done.

---

## 13. What went wrong along the way (and what it taught us)

These are real, and they are the most convincing things to talk about.

| What happened | What we learned |
|---|---|
| Our first scoring assumed edits make an image **more** uneven. The data showed the opposite: the polished and filtered photos were **smoother**, and some real photos scored higher than edited ones (accuracy 5/7, then 9/11). | Don't trust your first assumption. We printed the raw measurements, looked at the pattern, and redesigned the score around over-smoothing. After that it reached 11/11. |
| The test accuracy ignored the "others" images. | The helper looked for names starting with `other_`, but the files were named `others_`. A naming mismatch, not a logic bug. Check the small things first. |
| `AccessDenied` errors in CloudWatch for the upload Lambda. | IAM denies everything by default. Each Lambda needs exactly the permissions it uses, and the logs say which one is missing. |
| Browser CORS error when uploading to S3. | The browser blocks requests to another site unless that site says it's allowed. The bucket needed a CORS rule. |
| Opening `/scan` in the browser said "Not Found". | The address bar sends GET requests, but `/scan` accepts only POST. |
| "Mail app didn't open" on Request removal. | `mailto:` links need a default mail app. A Gmail compose link works in the browser instead. |
| The web dashboard on Amplify showed a 404. | The wrong zip was uploaded. Amplify needs `index.html` at the top level of the zip. |
| The API list looked empty in the console. | We were looking at the wrong region (Mumbai instead of N. Virginia). Everything in AWS is per-region. |
| The popup said "Server returned 404" for the profile. | The `/me` route hadn't been added in API Gateway yet. A 404 from the API means a missing route. |
| Making it multi-user: registering an email could fail if an older, unfiltered subscription for the same address already existed. | SNS won't create a second subscription with different settings. The old one had to be deleted first. |

---

## 14. Honest limitations (say these yourself, before anyone asks)

- **The score is a likelihood, not proof.** We tuned it on a small dataset, so it fits our test images. A stronger or different kind of edit could slip through, and an unusual real photo could be flagged.
- **It finds smoothing, not true deepfakes.** Our "edited" photos were AI-polished and filtered. A face swap or fully AI-generated face needs a trained detection model.
- **The internet is simulated.** A real version would need a crawler and a legal review.
- **The anonymous ID is not real authentication.** It keeps users' data apart, but anyone who gets an ID can act as that user, and clearing the browser loses access. Cognito sign-in is the production answer.
- **Anyone can type any email.** AWS sends that address a confirmation request and delivers nothing unless the owner confirms, but real accounts would prevent this.
- **Scaling.** The cost of a scan grows with users x images x photos. A real system would index each internet image once in a Rekognition face collection and search each user's photo against it. SNS also sends only plain-text email; Amazon SES would be used for branded emails.
- **Deleting data is manual** today. A signed-in "delete my data" button would automate it.

### What we would do next

1. Add real sign-in (Amazon Cognito).
2. Replace the forensic score with a trained deepfake-detection model, for example hosted on SageMaker.
3. Connect real sources (search results and social platforms, through their approved APIs).
4. Use a Rekognition face collection so scanning scales.
5. Send branded emails with Amazon SES.
6. Link each alert to the correct takedown form of the site it was found on.

---

## 15. Team roles (an equal split)

| | **Member 1: Detection** | **Member 2: Cloud backend** | **Member 3: Extension and project management** |
|---|---|---|---|
| **Builds** | `matchFaces` and `scoreManipulation`, and the Pillow layer | `scanPipeline`, API Gateway routes, `getAlerts`, `manageUser`, DynamoDB tables, SNS, EventBridge | The extension and dashboard (popup, alerts list, Scan now, email, photo upload, Request removal), `getUploadUrl` |
| **Tests and evidence** | Builds the test dataset, runs the accuracy tests, records the score table and the tuning story | Tests the flow end to end, checks each email and table row, works out the free-tier cost | Tests the extension on a fresh Chrome profile and checks every button and error message |
| **Project task** | Writes the demo script and runs the rehearsals | Draws the architecture diagram and handles the demo reset | Manages the GitHub repo and builds the slides from everyone's content |
| **Presents** | How face matching and the manipulation score work, and their limits | The architecture, why serverless, and how costs stay in the free tier | The problem, the extension walkthrough, and future work |

Make the table match who really did each task before you present it.

---

## 16. Check your own understanding

If you can answer these in your own words, you understand the project.

1. **Why are there two kinds of images?** Reference photos say who to look for, and dataset images are what gets looked through.
2. **Why does an uploaded reference photo never create an alert?** Alerts only come from the dataset. References are only comparison examples.
3. **How does the system know whose photos to use?** The popup sends the user's anonymous ID with every request, and the backend only reads photos in `users/<that ID>/`.
4. **Why is the ID not real login?** It's a random value kept in the browser. It separates users but doesn't prove who someone is, so production would use Cognito.
5. **How does an email reach only the right person?** Each address is subscribed with a filter, and each alert is published tagged with the owner's address, so SNS delivers it only there.
6. **Why was no email sent when you scanned twice?** The images already had rows in that user's alerts, so they weren't new.
7. **Why take the highest score across the reference photos?** If any one of them recognizes the face, it's a match.
8. **Why isn't the extension given AWS keys?** Anything inside a browser can be read, so the extension only gets short-lived, single-purpose tickets.
9. **Why did we write our own detection rather than use Rekognition for it?** Rekognition recognizes faces, but it can't tell if an image was edited.
10. **What would break if you forgot to delete the alert rows before the demo?** The live images wouldn't count as new, so no email would be sent.
11. **What does the daily schedule do now?** It scans every registered user who has reference photos, using each user's own photos.
12. **What is the weakest part of the project, and why?** The manipulation score: it's tuned to a small dataset and catches smoothing, not every kind of deepfake.

---

## Quick reference

| Item | Value |
|---|---|
| Region | US East (N. Virginia), us-east-1 |
| Reference bucket | `faceguard-reference-images`, photos in `users/<ID>/` |
| Tables | `FaceGuardUsers` (key: userId), `FaceGuardAlertsByUser` (keys: userId + imageId) |
| SNS topic | `faceguard-alerts` (one filtered email subscription per user) |
| Face match threshold | 90% similarity |
| Manipulation threshold | 48 out of 100 |
| Photo limit | 5 reference photos per user, 5 MB each, JPG or PNG |
| Upload ticket lifetime | 5 minutes |
| API throttling | rate 5, burst 10 |
| API time limit | 30 seconds per request |
| Schedule | EventBridge Scheduler, once a day (disabled during the demo) |
| Extension version | 0.5.0 |
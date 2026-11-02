# Face recognition update — 2 November 2026

Later change: at the user's request, head movement is temporarily disabled. The current eye-only flow uses 10 frames / 1.2 seconds in quick mode and 16 frames / 2.4 seconds in guided mode, with face engine version 3. No tests or benchmarks were run for this later change. The timings and test results below describe the earlier two-action flow.

## What changed

New enrollments use OpenCV YuNet/SFace, with three to five consistent templates per voter. Enrollment and login use the same alignment/model. Templates are explicitly versioned so old dlib vectors can never accidentally be compared with SFace vectors. The old dlib path remains available for existing profiles; a fresh enrollment is required to enable the faster path.

Every submitted frame still receives face-count, identity and landmark analysis. The models run inside the existing warmed process pool. YuNet uses a bounded preview for detection while SFace aligns/encodes the full-resolution frame. Model artifacts are pinned to an OpenCV Zoo revision and SHA-256 checked before API readiness. No network downloads occur during authentication.

The new matching rule uses median cosine similarity across the stored templates, with an initial threshold of 0.50. The old dlib Euclidean threshold stays at 0.55. These numbers are model-specific and cannot be compared as equivalent strengths. The SFace threshold is above the 0.363 LFW example in the [OpenCV tutorial](https://docs.opencv.org/5.0/tutorials/dnn/dnn_face/dnn_face.html), but still needs calibration with consented real users and attack samples before any production claim.

## Recognition failures addressed

- A pending replacement no longer blocks the still-active identity. The replacement itself cannot authenticate until approved. Mismatching login with a pending replacement explains that the previous profile is still active.
- Login shows whether the updated profile is active or pending. The server records activation time and invalidates prior sessions on approval. Malformed replacement profiles are rejected before activation.
- The old blink baseline could overlap a deliberate eye closure and falsely reject the action requested by the UI. Validation now requires open eyes at both ends and a bilateral closure between them, including longer closures. Static closed eyes, a wink and missing reopening still fail.
- Movement errors explicitly say that the face matched, distinguishing liveness failure from identity mismatch.
- Full-frame background blur during a requested head movement no longer preempts face detection and matching. Enrollment retains sharpness checks; detection and identity still check every login frame.
- Enrollment chooses a consistent majority of samples instead of anchoring all decisions to the first frame. Equal mixed-identity groups fail.
- A newly loaded frontend detects an old backend before capture and provides restart instructions. Previously this mismatch could leave users repeatedly trying an unchanged recognition path.
- Relative database paths now resolve against the backend directory. Launching from the repository root or the demo therefore cannot silently select different enrollment databases.

These fix identifiable failure paths. The user's exact rejection message and live webcam sequence were not available, so successful recognition of that individual has not been demonstrated.

## Timing evidence

Quick capture records 20 observations in two ordered windows totaling **2.4 seconds**. Three native runs on the local i5-9300H laptop processed all 20 frames in **0.6659, 0.6399 and 0.5875 seconds**. Capture plus native inference is therefore about three seconds, excluding upload, decode/replay, DB work and browser scheduling. It is not a guaranteed 2–3 second end-to-end result.

The benchmark used three public example photos: two photos of one person scored 0.764, while the different-person example scored 0.082 (threshold 0.50). This is a smoke check, not an accuracy study. Repeated benchmark images cannot pass the application's replay/liveness checks. [Raw results and input hashes](fast-face-benchmark-2026-11-02.json) are reproducible with:

```powershell
server/face-recognition/.venv/Scripts/python.exe server/face-recognition/benchmark_fast_face.py --output docs/security/fast-face-benchmark-2026-11-02.json
```

The **Give me more time for the movements** option and spoken guidance use longer capture windows. Existing dlib profiles also keep the guided path and its slower inference until updated.

## Using the new path

1. Start the updated demo and refresh the browser. `/health` should report `face_engine_version: 2`.
2. Capture a new face enrollment under the same voter ID. The new model needs new images; old vectors cannot be converted.
3. An administrator checks the voter ID and selects **Approve face update**. An existing eligibility approval is retained; new voters still need eligibility approval.
4. Return to login. It should say the updated profile is active. Use the longer guidance option if the quick prompts are difficult.

No existing templates, eligibility records or ballot history are deleted by this migration. Raw images are not retained. New templates remain sensitive biometric data subject to the same database/backup protections as the previous embeddings.

## Validation

- **85 backend tests passed**, including legacy compatibility, versioned-template validation, pending-to-active migration, session invalidation, identity substitution, quick challenge duration/frame binding, longer eye closure, model tampering, native worker crash/recovery, API startup/shutdown, and existing blockchain integration.
- After adding the launch-directory regression, all **19 profile-focused tests** passed, including that new check.
- **32 frontend tests passed**, including quick/guided capture ordering, frozen-camera cancellation, approval feedback, old-backend detection and HTTP timeout/retry.
- ESLint, TypeScript/production build, Solidity prebuild and launcher syntax checks passed. Existing dependency deprecation and large-bundle/eval warnings remain.
- Model binaries were downloaded and checked against their pinned digests; the public-photo benchmark used the actual native models.
- The local demo was started successfully. Truffle reported the network up to date; the backend warmed four workers, `/health` returned `face_engine_version: 2`, and `/login` returned HTTP 200. The existing database and chain were reused.
- No physical webcam evaluation, population accuracy calibration, sophisticated spoof campaign, Docker build or production deployment was performed.

Changed areas: model installer/manifest and licenses; versioned profile parsing/matching; worker inference; enrollment/login/approval; liveness timing/validation; camera capture/login feedback; registration resizing/status; offline enrollment; demo/Makefile/Docker model setup; tests and documentation.

# Face login performance follow-up

The slow path performed 32 consecutive dlib identity inferences after camera capture. This Windows installation has no dlib BLAS/CUDA acceleration. Batching alone did not help, so login now uses four persistent, isolated CPU processes, warmed before the API accepts traffic. Native dlib calls remain sequential inside each process. Enrollment continues to use its existing serialized path.

## Measured result

On this machine (Intel i5-9300H, four physical cores, 8 GB RAM), three native benchmark rounds produced:

| Measurement | Previous | Updated |
| --- | ---: | ---: |
| Submitted frames | 32 | 24 |
| Scheduled camera capture | 4.8 seconds plus encoding overhead | 3.6 seconds including encoding time within sampling intervals |
| Median detection/landmarks/identity processing | 19.711 seconds | 4.981 seconds |
| Processing range over three runs | 16.717–20.802 seconds | 4.683–6.236 seconds |

That is approximately **75% less native processing wait** in this benchmark. Worker startup took 5.065 seconds, paid before API readiness rather than on the first voter. Embeddings were identical to the old path (maximum L2 distance 0.0); required landmarks also matched exactly. Raw results and the input hash are in [face-performance-benchmark.json](face-performance-benchmark.json).

This is a repeated public still-image benchmark, not a camera login or biometric accuracy measurement. The repeated image cannot pass the application's replay/liveness checks. Network upload, decoding/quality/replay checks and real human movement are outside these timings. Real login latency and false-reject performance need a physical webcam check.

## Behavior and protections

- Every submitted observation still receives face-count, landmark and identity analysis. Detection resolution, upsampling, alignment model, 128D identity model and match threshold are preserved. A face substitution in the middle of the sequence still fails authentication.
- Capture uses two ordered windows with explicit head-turn and eye-close/open prompts. Deliberate closure gives the camera more opportunity to observe closed eyes than a quick spontaneous blink. Frozen camera output is rejected before upload, and navigation cancels capture promptly.
- Missing profiles, unapproved voters and an already-busy CV service are rejected before capture where possible. Concurrent expensive requests fail quickly instead of forming a long queue; a busy response may require retrying.
- Workers preserve frame ordering. Incomplete output, native errors, timeouts and process crashes cannot authenticate a voter. A broken pool is discarded and recreated on a later attempt. Slow batches use the same bounded pool rather than spawning more processes.
- Inference has a configurable 15-second deadline. The browser aborts an attempt after 30 seconds and restores retry controls. Timings are logged and returned in `Server-Timing`; images and embeddings are not logged or saved.

## Validation executed

- Backend: **62 tests passed**, including native worker crash/recovery, real API startup/shutdown with warmed workers, incomplete/failed inference, preflight, identity substitution, liveness/replay, and existing Ganache integration.
- Frontend: **27 tests passed**, including all four prompt orders/directions, capture cancellation/frozen-camera detection, approval preflight, HTTP timeout/retry, and the existing tests.
- ESLint, TypeScript, production build/Solidity prebuild and `git diff --check` passed. Existing dependency deprecation, large-bundle and `vm-browserify` warnings remain.
- The benchmark ran three rounds using `benchmark_face.py --download-example --workers 4 --rounds 3 --output docs/security/face-performance-benchmark.json`. It downloads the face_recognition project's public example into memory and does not access the voter DB.

## Activation and configuration

The running `npm run demo` backend does not auto-reload Python changes. Stop it in its terminal with **Ctrl+C**, run **`npm run demo`** again, wait for backend readiness, and refresh the browser. The launcher preserves the existing chain and election; do not add migration reset flags. No voter re-enrollment is required.

`FACE_WORKERS` defaults to up to four processes. Set it to 2 on constrained machines. Use one Uvicorn API process on a laptop, because each API process owns its own pool. `FACE_PROCESSING_TIMEOUT_SECONDS` controls the inference deadline. The current running demo and its live database/election were left running during this follow-up.

Files changed for this follow-up: backend `main.py`, `config.py`, `test_main.py`, `test_security.py`, new `face_workers.py`, `test_face_workers.py`, `benchmark_face.py`; frontend `VoterLogin.tsx`, new `livenessCapture.ts`, its tests and `VoterLogin.performance.test.tsx`; environment examples, README, and this report/benchmark artifact. Existing login form/paste tests were retained.

Implementation references: [face_recognition's model/alignment implementation](https://github.com/ageitgey/face_recognition/blob/master/face_recognition/api.py) and [dlib descriptor interfaces](https://dlib.net/python/index.html). The optimization preserves those model semantics rather than changing identity thresholds.

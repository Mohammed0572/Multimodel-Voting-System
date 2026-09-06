# MediaPipe assets for in-browser blink detection

The browser detector loads both assets from this app's own origin.

## WASM runtime

Run `npm install` to copy the WASM runtime bundled in
`@mediapipe/tasks-vision` into `public/mediapipe/wasm/` automatically.

## Face Landmarker model

Download Google's pretrained model once and place it at
`public/mediapipe/face_landmarker.task`:

```bash
curl -L -o public/mediapipe/face_landmarker.task https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task
```

The model is about 3.6 MB and is not included in the npm package.

If the model or WASM runtime is unavailable, voter login automatically falls
back to the fixed-interval capture path. The server remains authoritative for
face matching and EAR-based liveness validation.

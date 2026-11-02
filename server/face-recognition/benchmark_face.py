"""Opt-in native benchmark; no voter database, credentials or saved images.

Run with --download-example for the face_recognition project's public example,
or --image PATH for an operator-owned image. This is not an accuracy/PAD test.
"""
import argparse
import hashlib
import json
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--image", type=Path)
    source.add_argument("--download-example", action="store_true")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    import cv2
    import numpy as np
    import face_recognition as fr
    from face_workers import FaceWorkers
    if args.download_example:
        from urllib.request import urlopen
        url = "https://raw.githubusercontent.com/ageitgey/face_recognition/master/examples/obama.jpg"
        with urlopen(url, timeout=30) as response:
            raw = response.read()
    else:
        raw = args.image.read_bytes()
    image = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("Could not decode benchmark image")
    height, width = image.shape[:2]
    image = cv2.resize(image, (round(width*640/max(height,width)), round(height*640/max(height,width))))

    def old_frame(image):
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        scale = .5 if min(image.shape[:2]) >= 320 else 1
        small = cv2.resize(rgb, (0, 0), fx=scale, fy=scale) if scale != 1 else rgb
        locations = fr.face_locations(small, model="hog")
        if len(locations) != 1:
            raise ValueError("Benchmark requires exactly one detectable face")
        locations = [tuple(int(coord/scale) for coord in location) for location in locations]
        landmarks = fr.face_landmarks(rgb, locations)[0]
        return fr.face_encodings(rgb, locations)[0], landmarks

    pool = FaceWorkers(args.workers, timeout=60)
    started = time.perf_counter()
    pool.start()
    startup = time.perf_counter()-started
    samples = []
    try:
        reference, landmarks = old_frame(image)
        for _ in range(args.rounds):
            started = time.perf_counter()
            old = [old_frame(image) for _ in range(32)]
            old_time = time.perf_counter()-started
            started = time.perf_counter()
            new = pool.analyze([image]*24)
            new_time = time.perf_counter()-started
            distance = max(float(np.linalg.norm(item[0]-reference)) for item in new)
            assert all(item[1] == {key: landmarks[key] for key in item[1]} for item in new)
            assert len(old) == 32 and len(new) == 24 and distance < 1e-6
            sample = {"previous_32_frames_s": round(old_time,3), "optimized_24_frames_s": round(new_time,3), "embedding_max_distance": distance}
            samples.append(sample)
            print(json.dumps(sample), flush=True)
    finally:
        pool.close()
    report = {"source": url if args.download_example else "operator-provided image (path omitted)",
              "image_sha256": hashlib.sha256(raw).hexdigest(), "image_dimensions": list(image.shape[:2]),
              "workers": args.workers, "startup_s": round(startup,3), "runs": samples,
              "scope": "Repeated public still image, native detection/landmarks/embedding only. Does not pass live login; no camera, network, queue, accuracy or spoof-resistance measurement."}
    if args.output:
        args.output.write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()

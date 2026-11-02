"""Opt-in public example benchmark; never reads voter data or claims a live login."""
import argparse
import hashlib
import json
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    from urllib.request import urlopen
    import cv2
    import numpy as np
    from face_workers import FaceWorkers
    from face_profiles import SFACE_MODEL, build_profile, parse_profile, matches_sface
    images, hashes = [], {}
    for name in ("obama", "obama2", "biden"):
        with urlopen(f"https://raw.githubusercontent.com/ageitgey/face_recognition/master/examples/{name}.jpg", timeout=30) as response:
            raw = response.read()
        hashes[name] = hashlib.sha256(raw).hexdigest()
        image = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        h, w = image.shape[:2]
        images.append(cv2.resize(image, (round(w*640/max(h,w)), round(h*640/max(h,w)))))
    pool = FaceWorkers(4, timeout=30)
    try:
        pool.start()
        observations = pool.analyze(images, model=SFACE_MODEL)
        assert all(item is not None for item in observations)
        _, templates = parse_profile(json.dumps(build_profile([observations[0][0]]*3)))
        same, same_score = matches_sface(templates, observations[1][0])
        other, other_score = matches_sface(templates, observations[2][0])
        assert same and not other
        timings = []
        for _ in range(3):
            started = time.perf_counter()
            result = pool.analyze([images[0]]*20, model=SFACE_MODEL)
            assert len(result) == 20 and all(matches_sface(templates, item[0])[0] for item in result)
            timings.append(round(time.perf_counter()-started, 4))
            print(f"20-frame fast inference: {timings[-1]}s", flush=True)
        report = {"model": SFACE_MODEL, "workers": 4, "inference_20_frames_s": timings,
                  "scheduled_capture_s": 2.4, "same_person_two_photos_cosine": same_score,
                  "different_person_cosine": other_score, "threshold": .5, "input_sha256": hashes,
                  "scope": "Three public example photographs, not a biometric accuracy study. Native processing excludes camera, upload, decode/replay and DB time. Repeated still frames cannot pass live authentication."}
        args.output.write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8")
    finally:
        pool.close()


if __name__ == "__main__":
    main()

"""Pinned OpenCV model artifacts. No network downloads during authentication."""
import hashlib
from functools import lru_cache
from pathlib import Path

MODEL_DIR = Path(__file__).resolve().with_name("models")
REVISION = "48b10fa505aeb51fbd127fc60a5c660040e823b7"
MODELS = {
    "yunet": ("face_detection_yunet", "face_detection_yunet_2023mar.onnx", "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"),
    "sface": ("face_recognition_sface", "face_recognition_sface_2021dec.onnx", "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79"),
}


@lru_cache(maxsize=2)
def model_path(name):
    _, filename, expected = MODELS[name]
    path = MODEL_DIR / filename
    if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise RuntimeError("Face models are missing or invalid. Run face_models.py before starting the API.")
    return str(path)


def install():
    from urllib.request import urlopen
    MODEL_DIR.mkdir(exist_ok=True)
    for name, (folder, filename, digest) in MODELS.items():
        path = MODEL_DIR / filename
        if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == digest:
            continue
        url = f"https://media.githubusercontent.com/media/opencv/opencv_zoo/{REVISION}/models/{folder}/{filename}"
        with urlopen(url, timeout=90) as response:
            data = response.read(50_000_000)
        if hashlib.sha256(data).hexdigest() != digest:
            raise RuntimeError(f"Invalid downloaded model: {name}")
        temporary = path.with_suffix(".download")
        temporary.write_bytes(data)
        temporary.replace(path)
        with urlopen(f"https://raw.githubusercontent.com/opencv/opencv_zoo/{REVISION}/models/{folder}/LICENSE", timeout=30) as response:
            (MODEL_DIR / f"{name}-LICENSE.txt").write_bytes(response.read())
        print(f"Installed verified {name} model.", flush=True)


if __name__ == "__main__":
    install()

from __future__ import annotations

import pickle
from pathlib import Path
from typing import Iterable, Sequence

import cv2
import face_recognition
import numpy as np


ENCODINGS_PATH = Path(__file__).resolve().with_name("encodings.pkl")

# Optimization: process quarter-size frames so HOG detection and face encodings
# run on 25% of the original width/height while the full frame remains on screen.
DEFAULT_FRAME_SCALE = 0.25

# Optimization: keep webcam capture modest so OpenCV has fewer pixels to move,
# convert, and display on every real-time frame.
DEFAULT_CAMERA_WIDTH = 640
DEFAULT_CAMERA_HEIGHT = 480

# Optimization: HOG is much lighter than CNN on CPU webcams and avoids the
# latency spikes that make live feeds feel delayed.
DEFAULT_DETECTION_MODEL = "hog"

# Optimization: process every alternate frame and reuse the last result on the
# skipped frame so the display can keep repainting smoothly.
DEFAULT_PROCESS_EVERY_N_FRAMES = 2


def clean_name(name: str) -> str:
    """Normalize and validate a display name."""
    cleaned = " ".join(name.strip().split())
    if not cleaned:
        raise ValueError("Name cannot be empty.")
    return cleaned


def load_encodings(path: Path = ENCODINGS_PATH) -> dict[str, list]:
    """Load saved face encodings from disk."""
    if not path.exists():
        return {"encodings": [], "names": []}

    with path.open("rb") as file:
        data = pickle.load(file)

    encodings = data.get("encodings", [])
    names = data.get("names", [])
    if len(encodings) != len(names):
        raise ValueError(f"Invalid encoding store: {path}")

    return {
        "encodings": [np.asarray(encoding) for encoding in encodings],
        "names": [str(name) for name in names],
    }


def save_encodings(data: dict[str, list], path: Path = ENCODINGS_PATH) -> None:
    """Persist face encodings to disk."""
    encodings = data.get("encodings", [])
    names = data.get("names", [])
    if len(encodings) != len(names):
        raise ValueError("Encodings and names must have the same length.")

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as file:
        pickle.dump({"encodings": encodings, "names": names}, file)


def save_user_encoding(
    name: str,
    encoding: np.ndarray,
    path: Path = ENCODINGS_PATH,
    replace_existing: bool = True,
) -> int:
    """Add or replace a user's face encoding and return total saved users."""
    user_name = clean_name(name)
    data = load_encodings(path)

    if replace_existing:
        kept = [
            (saved_name, saved_encoding)
            for saved_name, saved_encoding in zip(data["names"], data["encodings"])
            if saved_name.lower() != user_name.lower()
        ]
        data["names"] = [saved_name for saved_name, _ in kept]
        data["encodings"] = [saved_encoding for _, saved_encoding in kept]

    data["names"].append(user_name)
    data["encodings"].append(np.asarray(encoding))
    save_encodings(data, path)
    return len(data["names"])


def open_camera(
    camera_index: int = 0,
    width: int = DEFAULT_CAMERA_WIDTH,
    height: int = DEFAULT_CAMERA_HEIGHT,
) -> cv2.VideoCapture:
    """Open a webcam and fail fast when it is unavailable."""
    camera = cv2.VideoCapture(camera_index)
    if not camera.isOpened():
        raise RuntimeError(f"Could not open webcam at index {camera_index}.")

    # Optimization: ask the webcam for 640x480 frames to reduce capture and
    # display work before any recognition logic runs.
    camera.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    camera.set(cv2.CAP_PROP_FRAME_HEIGHT, height)

    # Optimization: keep the capture buffer short so a slow processed frame
    # does not leave the UI showing old webcam frames.
    camera.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return camera


def validate_frame_scale(frame_scale: float) -> None:
    if frame_scale <= 0 or frame_scale > 1:
        raise ValueError("Frame scale must be greater than 0 and at most 1.")


def resize_for_recognition(frame: np.ndarray, frame_scale: float) -> np.ndarray:
    """Shrink and convert a BGR OpenCV frame to RGB for face_recognition."""
    validate_frame_scale(frame_scale)
    resized = cv2.resize(frame, (0, 0), fx=frame_scale, fy=frame_scale)
    return cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)


def detect_faces(
    frame: np.ndarray,
    model: str = DEFAULT_DETECTION_MODEL,
    frame_scale: float = DEFAULT_FRAME_SCALE,
) -> tuple[list[tuple[int, int, int, int]], list[np.ndarray]]:
    """Return face locations and encodings from an OpenCV BGR frame."""
    rgb_frame = resize_for_recognition(frame, frame_scale)
    locations = find_face_locations(rgb_frame, model)
    encodings = encode_face_locations(rgb_frame, locations)
    return locations, encodings


def find_face_locations(
    rgb_frame: np.ndarray,
    model: str = DEFAULT_DETECTION_MODEL,
) -> list[tuple[int, int, int, int]]:
    """Locate faces in an RGB frame already prepared for face_recognition."""
    return face_recognition.face_locations(rgb_frame, model=model)


def limit_to_primary_face(
    locations: Sequence[tuple[int, int, int, int]],
) -> list[tuple[int, int, int, int]]:
    """Return only the largest detected face for real-time processing."""
    if not locations:
        return []

    # Optimization: landmark and encoding work scales with face count, so keep
    # only the largest/closest face and ignore bystanders.
    primary = max(locations, key=_face_area)
    return [primary]


def find_face_landmarks(
    rgb_frame: np.ndarray,
    locations: Sequence[tuple[int, int, int, int]],
) -> list[dict[str, list[tuple[int, int]]]]:
    """Return facial landmarks for already detected face locations."""
    return face_recognition.face_landmarks(rgb_frame, locations)


def encode_face_locations(
    rgb_frame: np.ndarray,
    locations: Sequence[tuple[int, int, int, int]],
) -> list[np.ndarray]:
    """Compute face encodings only after liveness checks have passed."""
    return face_recognition.face_encodings(rgb_frame, locations)


def scale_location(
    location: Sequence[int],
    frame_scale: float = DEFAULT_FRAME_SCALE,
) -> tuple[int, int, int, int]:
    """Scale a face_recognition location back to the original frame size."""
    validate_frame_scale(frame_scale)
    top, right, bottom, left = location
    scale = 1 / frame_scale
    return (
        int(top * scale),
        int(right * scale),
        int(bottom * scale),
        int(left * scale),
    )


def _face_area(location: Sequence[int]) -> int:
    top, right, bottom, left = location
    return max(0, right - left) * max(0, bottom - top)


def draw_face_box(
    frame: np.ndarray,
    location: Sequence[int],
    label: str,
    frame_scale: float = DEFAULT_FRAME_SCALE,
    color: tuple[int, int, int] = (0, 255, 0),
) -> None:
    """Draw a labeled face bounding box on an OpenCV frame."""
    top, right, bottom, left = scale_location(location, frame_scale)

    cv2.rectangle(frame, (left, top), (right, bottom), color, 2)
    label_top = max(bottom - 30, top)
    cv2.rectangle(frame, (left, label_top), (right, bottom), color, cv2.FILLED)
    cv2.putText(
        frame,
        label,
        (left + 6, bottom - 8),
        cv2.FONT_HERSHEY_DUPLEX,
        0.55,
        (255, 255, 255),
        1,
    )


def average_encodings(encodings: Iterable[np.ndarray]) -> np.ndarray:
    """Average multiple captures into one stable user encoding."""
    collected = [np.asarray(encoding) for encoding in encodings]
    if not collected:
        raise ValueError("At least one face encoding is required.")
    return np.mean(collected, axis=0)


def match_face(
    face_encoding: np.ndarray,
    known_encodings: Sequence[np.ndarray],
    known_names: Sequence[str],
    tolerance: float = 0.5,
) -> tuple[str, float | None]:
    """Return the best matching name and distance for a face encoding."""
    if not known_encodings:
        return "Unknown", None

    distances = face_recognition.face_distance(known_encodings, face_encoding)
    best_index = int(np.argmin(distances))
    best_distance = float(distances[best_index])

    if best_distance <= tolerance:
        return known_names[best_index], best_distance
    return "Unknown", best_distance

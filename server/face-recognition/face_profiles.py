"""Versioned templates: dlib and SFace vectors are never interchangeable."""
import json
import numpy as np

SFACE_MODEL = "sface-2021dec-v1"
DLIB_MODEL = "dlib-128-v1"
# A conservative initial threshold above OpenCV's LFW example (0.363).
# This is not a calibrated election population false-accept guarantee.
SFACE_THRESHOLD = 0.50


def unit_vector(value):
    vector = np.asarray(value, dtype=np.float32)
    if vector.shape != (128,) or not np.isfinite(vector).all():
        raise ValueError("Invalid face template")
    norm = float(np.linalg.norm(vector))
    if not np.isfinite(norm) or norm < 1e-6:
        raise ValueError("Empty face template")
    return vector / norm


def parse_profile(encoded):
    value = json.loads(encoded)
    if isinstance(value, list):
        vector = np.asarray(value, dtype=np.float32)
        unit_vector(vector)  # Validate but keep dlib's original Euclidean scale.
        return DLIB_MODEL, [vector]
    if not isinstance(value, dict) or value.get("model") != SFACE_MODEL:
        raise ValueError("Unknown face template model")
    templates = value.get("templates")
    if not isinstance(templates, list) or not 3 <= len(templates) <= 5:
        raise ValueError("Invalid template count")
    return SFACE_MODEL, [unit_vector(item) for item in templates]


def build_profile(embeddings):
    if not 3 <= len(embeddings) <= 10:
        raise ValueError("At least three clear face samples are required.")
    vectors = np.stack([unit_vector(item) for item in embeddings])
    similarities = vectors @ vectors.T
    groups = similarities >= .65
    medoid = int(np.argmax(groups.sum(axis=1)))
    selected = vectors[groups[medoid]]
    if len(selected) < max(3, len(vectors)//2+1):
        raise ValueError("Face samples are inconsistent. Keep only your face in view.")
    return {"model": SFACE_MODEL, "templates": selected[:5].tolist()}


def matches_sface(templates, embedding):
    scores = np.stack(templates) @ unit_vector(embedding)
    score = float(np.median(scores))
    return score >= SFACE_THRESHOLD, score

"""Persistent, isolated CPU workers for the existing dlib face models.

This module does not load the API, open its database, or save biometric files.
Each process owns its models; native dlib calls never run concurrently within it.
"""
import os
import multiprocessing
from concurrent.futures import ProcessPoolExecutor, TimeoutError
from concurrent.futures.process import BrokenProcessPool
from threading import Lock
from itertools import repeat

import cv2
import numpy as np

_models = None
_fast_models = None


def initialize_worker(ready_barrier=None):
    global _models
    import dlib
    import face_recognition_models as paths
    cv2.setNumThreads(1)
    _models = (
        dlib.get_frontal_face_detector(),
        dlib.shape_predictor(paths.pose_predictor_model_location()),
        dlib.shape_predictor(paths.pose_predictor_five_point_model_location()),
        dlib.face_recognition_model_v1(paths.face_recognition_model_location()),
    )
    # Pay initial inference allocation at startup, before accepting logins.
    _models[3].compute_face_descriptor(np.zeros((150, 150, 3), dtype=np.uint8), 0)
    if ready_barrier is not None:
        # Verify installed artifacts at startup. A model is never fetched on a
        # request and profiles cannot silently fall back to another model.
        fast_models()
        ready_barrier.wait(timeout=60)


def worker_ready():
    return os.getpid()


class FrameError(ValueError):
    """Safe, user-facing frame rejection; survives process serialization."""


def analyze_frame(image):
    import dlib
    if _models is None:
        initialize_worker()
    detector, landmark_model, alignment_model, encoder = _models
    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    height, width = rgb.shape[:2]
    if min(height, width) < 80:
        return None
    scale = 0.5 if min(height, width) >= 320 else 1.0
    small = rgb if scale == 1 else cv2.resize(rgb, (0, 0), fx=scale, fy=scale)
    # Preserve the previous detector's scale and upsampling: smaller extra
    # faces must not disappear just to obtain a faster benchmark.
    locations = detector(small, 1)
    if not locations:
        return None
    if len(locations) != 1:
        raise FrameError("Only one face must be visible.")
    location = locations[0]
    top = int(max(location.top(), 0) / scale)
    right = int(min(location.right(), small.shape[1]) / scale)
    bottom = int(min(location.bottom(), small.shape[0]) / scale)
    left = int(max(location.left(), 0) / scale)
    if min(right-left, bottom-top) < 80:
        raise FrameError("Move closer. Your face is too small in the image.")
    rectangle = dlib.rectangle(left, top, right, bottom)
    points = [(point.x, point.y) for point in landmark_model(rgb, rectangle).parts()]
    landmarks = {"left_eye": points[36:42], "right_eye": points[42:48], "nose_tip": points[31:36]}
    eye_left = np.mean(landmarks["left_eye"], axis=0)
    eye_right = np.mean(landmarks["right_eye"], axis=0)
    eye_width = float(np.linalg.norm(eye_right-eye_left))
    if eye_width < 10:
        raise FrameError("Move closer and look toward the camera.")
    yaw = (np.mean(landmarks["nose_tip"], axis=0)[0] - (eye_left[0]+eye_right[0])/2) / eye_width
    if abs(yaw) > .65:
        raise FrameError("Look toward the camera; avoid turning too far.")
    # Exactly the original five-point alignment, 128D model and default padding.
    embedding = np.asarray(encoder.compute_face_descriptor(rgb, alignment_model(rgb, rectangle), 1))
    return embedding, landmarks


def fast_models():
    global _fast_models
    if _fast_models is None:
        from face_models import model_path
        detector = cv2.FaceDetectorYN.create(model_path("yunet"), "", (320, 320), .85, .3, 100)
        recognizer = cv2.FaceRecognizerSF.create(model_path("sface"), "")
        recognizer.feature(np.zeros((112, 112, 3), dtype=np.uint8))
        _fast_models = detector, recognizer
    return _fast_models


def analyze_fast_frame(image):
    """All observations get one-face, identity and 68-point liveness checks."""
    import dlib
    if _models is None:
        initialize_worker()
    detector, recognizer = fast_models()
    height, width = image.shape[:2]
    # YuNet detects on a bounded preview; align/encode from full resolution.
    # An accepted 80px face remains at least 40px in a 640px camera frame.
    scale = min(1.0, 320 / max(height, width))
    preview = cv2.resize(image, (round(width*scale), round(height*scale))) if scale < 1 else image
    detector.setInputSize((preview.shape[1], preview.shape[0]))
    _, faces = detector.detect(preview)
    if faces is None or len(faces) == 0:
        return None
    if len(faces) != 1:
        raise FrameError("Only one face must be visible.")
    face = faces[0].copy()
    face[:14] /= scale
    x, y, w, h = [float(v) for v in face[:4]]
    if min(w, h) < 80:
        raise FrameError("Move closer. Your face is too small in the image.")
    if x < 0 or y < 0 or x+w > width or y+h > height:
        raise FrameError("Keep your whole face inside the camera view.")
    aligned = recognizer.alignCrop(image, face)
    embedding = recognizer.feature(aligned).reshape(-1).copy()
    rectangle = dlib.rectangle(round(x), round(y), round(x+w), round(y+h))
    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    points = [(p.x, p.y) for p in _models[1](rgb, rectangle).parts()]
    landmarks = {"left_eye": points[36:42], "right_eye": points[42:48], "nose_tip": points[31:36]}
    return embedding, landmarks


def analyze_versioned_frame(image, model):
    from face_profiles import SFACE_MODEL, DLIB_MODEL
    if model == SFACE_MODEL:
        return analyze_fast_frame(image)
    if model == DLIB_MODEL:
        return analyze_frame(image)
    raise FrameError("Unsupported face profile. Ask an administrator to review it.")


class FaceWorkers:
    def __init__(self, workers=4, timeout=15):
        self.workers = workers
        self.timeout = timeout
        self._pool = None
        self._lock = Lock()

    def _get_pool(self):
        with self._lock:
            if self._pool is None:
                self._pool = ProcessPoolExecutor(
                    max_workers=self.workers,
                    mp_context=multiprocessing.get_context("spawn"),
                    initializer=initialize_worker,
                    initargs=(multiprocessing.get_context("spawn").Barrier(self.workers),),
                )
            return self._pool

    def start(self):
        pool = self._get_pool()
        # Submission starts all processes. Await their initializer/inference.
        try:
            futures = [pool.submit(worker_ready) for _ in range(self.workers)]
            for future in futures:
                future.result(timeout=65)
        except Exception:
            self.close(wait=False)
            raise

    def analyze(self, images, model="dlib-128-v1"):
        pool = self._get_pool()
        try:
            # map preserves capture order, even when CPU jobs finish out of order.
            return list(pool.map(analyze_versioned_frame, images, repeat(model), timeout=self.timeout, chunksize=1))
        except BrokenProcessPool:
            self.close(wait=False)
            raise RuntimeError("Face worker stopped; start a new live check.") from None
        except TimeoutError:
            # Do not create more workers while a slow batch is still running.
            raise RuntimeError("Face processing exceeded its time budget.") from None

    def close(self, wait=True):
        with self._lock:
            pool, self._pool = self._pool, None
        if pool is not None:
            pool.shutdown(wait=wait, cancel_futures=True)

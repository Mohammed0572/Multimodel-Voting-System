from __future__ import annotations

from dataclasses import dataclass
from math import dist
from time import monotonic
from typing import Iterable, Sequence


DEFAULT_EAR_THRESHOLD = 0.21
DEFAULT_REQUIRED_BLINKS = 2
DEFAULT_MIN_CLOSED_FRAMES = 3
DEFAULT_MAX_CLOSED_FRAMES = 5
DEFAULT_CHALLENGE_SECONDS = 10.0
DEFAULT_HEAD_MOVEMENT_RATIO = 0.03
DEFAULT_MAX_MISSING_FRAMES = 5

Point = tuple[int, int]
Landmarks = dict[str, list[Point]]
FaceLocation = tuple[int, int, int, int]
FrameShape = tuple[int, ...]


@dataclass
class LivenessResult:
    """Blink/liveness state after processing one video frame."""

    ear: float | None
    blink_detected: bool
    blink_count: int
    eyes_closed: bool
    closed_frames: int
    head_movement: float
    head_moved: bool
    elapsed_seconds: float
    time_remaining: float
    timed_out: bool
    face_detected: bool
    is_live: bool


def eye_aspect_ratio(eye_points: Sequence[Point]) -> float:
    """Calculate EAR from the 6 points returned for one eye."""
    vertical_1 = dist(eye_points[1], eye_points[5])
    vertical_2 = dist(eye_points[2], eye_points[4])
    horizontal = dist(eye_points[0], eye_points[3])

    if horizontal == 0:
        return 0.0

    # Open eyes have a larger vertical distance, so their EAR is higher.
    return (vertical_1 + vertical_2) / (2.0 * horizontal)


def average_eye_aspect_ratio(landmarks: Landmarks) -> float:
    """Return the average EAR for both eyes on one face."""
    left_ear = eye_aspect_ratio(landmarks["left_eye"])
    right_ear = eye_aspect_ratio(landmarks["right_eye"])
    return (left_ear + right_ear) / 2.0


def scale_points(points: Sequence[Point], frame_scale: float) -> list[Point]:
    """Scale landmark points from a resized frame back to the original frame."""
    scale = 1 / frame_scale
    return [(int(x * scale), int(y * scale)) for x, y in points]


class BlinkLivenessDetector:
    """Track blink, head movement, and timeout conditions for liveness."""

    def __init__(
        self,
        ear_threshold: float = DEFAULT_EAR_THRESHOLD,
        required_blinks: int = DEFAULT_REQUIRED_BLINKS,
        min_closed_frames: int = DEFAULT_MIN_CLOSED_FRAMES,
        max_closed_frames: int = DEFAULT_MAX_CLOSED_FRAMES,
        challenge_seconds: float = DEFAULT_CHALLENGE_SECONDS,
        head_movement_ratio: float = DEFAULT_HEAD_MOVEMENT_RATIO,
        max_missing_frames: int = DEFAULT_MAX_MISSING_FRAMES,
    ) -> None:
        if ear_threshold <= 0:
            raise ValueError("EAR threshold must be greater than 0.")
        if required_blinks < 1:
            raise ValueError("Required blinks must be at least 1.")
        if min_closed_frames < 1:
            raise ValueError("Minimum closed frames must be at least 1.")
        if max_closed_frames < min_closed_frames:
            raise ValueError("Maximum closed frames must be greater than or equal to minimum.")
        if challenge_seconds <= 0:
            raise ValueError("Challenge seconds must be greater than 0.")
        if head_movement_ratio <= 0:
            raise ValueError("Head movement ratio must be greater than 0.")
        if max_missing_frames < 0:
            raise ValueError("Maximum missing frames cannot be negative.")

        self.ear_threshold = ear_threshold
        self.required_blinks = required_blinks
        self.min_closed_frames = min_closed_frames
        self.max_closed_frames = max_closed_frames
        self.challenge_seconds = challenge_seconds
        self.head_movement_ratio = head_movement_ratio
        self.max_missing_frames = max_missing_frames

        self.reset()

    def reset(self) -> None:
        """Start a fresh liveness challenge."""
        self.blink_count = 0
        self.closed_frames = 0
        self.head_moved = False
        self.live_confirmed = False
        self.challenge_started_at: float | None = None
        self.baseline_center: tuple[float, float] | None = None
        self.missing_face_frames = 0

    def update(
        self,
        faces_landmarks: Iterable[Landmarks],
        face_locations: Sequence[FaceLocation] | None = None,
        frame_shape: FrameShape | None = None,
        now: float | None = None,
        frame_weight: int = 1,
    ) -> LivenessResult:
        """Process current face landmarks and return the latest liveness result."""
        if frame_weight < 1:
            raise ValueError("Frame weight must be at least 1.")

        current_time = monotonic() if now is None else now
        landmarks_list = list(faces_landmarks)
        locations = list(face_locations or [])
        primary_index = self._primary_face_index(locations)
        primary_landmarks = (
            landmarks_list[primary_index]
            if primary_index is not None and primary_index < len(landmarks_list)
            else (landmarks_list[0] if landmarks_list else None)
        )
        primary_location = locations[primary_index] if primary_index is not None else None

        face_detected = primary_landmarks is not None or primary_location is not None
        if not face_detected:
            return self._handle_missing_face(current_time, frame_weight)

        self.missing_face_frames = 0
        if self.challenge_started_at is None:
            self.challenge_started_at = current_time

        elapsed = current_time - self.challenge_started_at
        timed_out = elapsed > self.challenge_seconds and not self.live_confirmed
        time_remaining = max(0.0, self.challenge_seconds - elapsed)

        # Once the 10-second challenge has expired, keep denying until reset.
        if timed_out:
            return self._result(
                ear=None,
                blink_detected=False,
                eyes_closed=False,
                head_movement=0.0,
                elapsed_seconds=elapsed,
                time_remaining=time_remaining,
                timed_out=True,
                face_detected=True,
            )

        ear = average_eye_aspect_ratio(primary_landmarks) if primary_landmarks else None
        eyes_closed = ear is not None and ear < self.ear_threshold
        blink_detected = self._update_blink_count(eyes_closed, frame_weight)

        head_movement = 0.0
        if primary_location is not None and frame_shape is not None:
            head_movement = self._update_head_movement(primary_location, frame_shape)

        self.live_confirmed = (
            self.blink_count >= self.required_blinks and self.head_moved and not timed_out
        )

        return self._result(
            ear=ear,
            blink_detected=blink_detected,
            eyes_closed=eyes_closed,
            head_movement=head_movement,
            elapsed_seconds=elapsed,
            time_remaining=time_remaining,
            timed_out=False,
            face_detected=True,
        )

    def _update_blink_count(self, eyes_closed: bool, frame_weight: int = 1) -> bool:
        """Count blinks only after a valid closed-eye run has ended."""
        if eyes_closed:
            # Optimization support: when real-time loops skip alternate frames,
            # count the skipped frame too so blink duration thresholds stay stable.
            self.closed_frames += frame_weight
            return False

        blink_frames = self.closed_frames
        self.closed_frames = 0

        if self.min_closed_frames <= blink_frames <= self.max_closed_frames:
            self.blink_count += 1
            return True
        return False

    def _update_head_movement(
        self,
        location: FaceLocation,
        frame_shape: FrameShape,
    ) -> float:
        """Track whether the face center moved enough from its first position."""
        center = self._normalized_face_center(location, frame_shape)
        if self.baseline_center is None:
            self.baseline_center = center
            return 0.0

        movement = dist(self.baseline_center, center)
        if movement >= self.head_movement_ratio:
            self.head_moved = True
        return movement

    def _handle_missing_face(self, current_time: float, frame_weight: int = 1) -> LivenessResult:
        """Allow brief detector flicker, then reset the challenge if face is gone."""
        self.missing_face_frames += frame_weight
        if self.missing_face_frames > self.max_missing_frames:
            self.reset()

        elapsed = (
            0.0
            if self.challenge_started_at is None
            else current_time - self.challenge_started_at
        )
        return self._result(
            ear=None,
            blink_detected=False,
            eyes_closed=False,
            head_movement=0.0,
            elapsed_seconds=elapsed,
            time_remaining=max(0.0, self.challenge_seconds - elapsed),
            timed_out=False,
            face_detected=False,
            force_not_live=True,
        )

    def _result(
        self,
        ear: float | None,
        blink_detected: bool,
        eyes_closed: bool,
        head_movement: float,
        elapsed_seconds: float,
        time_remaining: float,
        timed_out: bool,
        face_detected: bool,
        force_not_live: bool = False,
    ) -> LivenessResult:
        return LivenessResult(
            ear=ear,
            blink_detected=blink_detected,
            blink_count=self.blink_count,
            eyes_closed=eyes_closed,
            closed_frames=self.closed_frames,
            head_movement=head_movement,
            head_moved=self.head_moved,
            elapsed_seconds=elapsed_seconds,
            time_remaining=time_remaining,
            timed_out=timed_out,
            face_detected=face_detected,
            is_live=False if force_not_live else self.live_confirmed,
        )

    @staticmethod
    def _primary_face_index(locations: Sequence[FaceLocation]) -> int | None:
        """Use the largest detected face as the liveness target."""
        if not locations:
            return None

        areas = [
            max(0, right - left) * max(0, bottom - top)
            for top, right, bottom, left in locations
        ]
        return int(max(range(len(areas)), key=areas.__getitem__))

    @staticmethod
    def _normalized_face_center(
        location: FaceLocation,
        frame_shape: FrameShape,
    ) -> tuple[float, float]:
        top, right, bottom, left = location
        height, width = frame_shape[:2]
        center_x = ((left + right) / 2.0) / max(width, 1)
        center_y = ((top + bottom) / 2.0) / max(height, 1)
        return center_x, center_y

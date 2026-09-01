from __future__ import annotations

"""Detect eye blinks from webcam video."""
import argparse

import cv2

from face_utils import (
    DEFAULT_DETECTION_MODEL,
    DEFAULT_FRAME_SCALE,
    DEFAULT_PROCESS_EVERY_N_FRAMES,
    find_face_landmarks,
    find_face_locations,
    limit_to_primary_face,
    open_camera,
    resize_for_recognition,
)
from liveness import (
    DEFAULT_CHALLENGE_SECONDS,
    DEFAULT_EAR_THRESHOLD,
    DEFAULT_HEAD_MOVEMENT_RATIO,
    DEFAULT_MAX_CLOSED_FRAMES,
    DEFAULT_MIN_CLOSED_FRAMES,
    DEFAULT_REQUIRED_BLINKS,
    BlinkLivenessDetector,
    Landmarks,
    scale_points,
)


def draw_eye_landmarks(frame, eye_points: list[tuple[int, int]]) -> None:
    for point in eye_points:
        cv2.circle(frame, point, 2, (0, 255, 0), -1)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Detect eye blinks from webcam video.")
    parser.add_argument("-c", "--camera", type=int, default=0, help="Webcam index.")
    parser.add_argument(
        "-t",
        "--threshold",
        type=float,
        default=DEFAULT_EAR_THRESHOLD,
        help="EAR value below which a blink is detected.",
    )
    parser.add_argument(
        "--required-blinks",
        type=int,
        default=DEFAULT_REQUIRED_BLINKS,
        help="Number of blinks required to confirm liveness.",
    )
    parser.add_argument(
        "--min-blink-frames",
        type=int,
        default=DEFAULT_MIN_CLOSED_FRAMES,
        help="Minimum consecutive closed-eye frames for one valid blink.",
    )
    parser.add_argument(
        "--max-blink-frames",
        type=int,
        default=DEFAULT_MAX_CLOSED_FRAMES,
        help="Maximum consecutive closed-eye frames for one valid blink.",
    )
    parser.add_argument(
        "--liveness-timeout",
        type=float,
        default=DEFAULT_CHALLENGE_SECONDS,
        help="Seconds allowed to complete blink and head-movement checks.",
    )
    parser.add_argument(
        "--head-movement-threshold",
        type=float,
        default=DEFAULT_HEAD_MOVEMENT_RATIO,
        help="Required normalized face-center movement for liveness.",
    )
    parser.add_argument(
        "--frame-scale",
        type=float,
        default=DEFAULT_FRAME_SCALE,
        help="Resize factor for faster detection. Default 0.25 processes 25%% frame size.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.threshold <= 0:
        raise SystemExit("--threshold must be greater than 0.")
    if args.required_blinks < 1:
        raise SystemExit("--required-blinks must be at least 1.")
    if args.min_blink_frames < 1:
        raise SystemExit("--min-blink-frames must be at least 1.")
    if args.max_blink_frames < args.min_blink_frames:
        raise SystemExit("--max-blink-frames must be greater than or equal to --min-blink-frames.")
    if args.liveness_timeout <= 0:
        raise SystemExit("--liveness-timeout must be greater than 0.")
    if args.head_movement_threshold <= 0:
        raise SystemExit("--head-movement-threshold must be greater than 0.")

    camera = open_camera(args.camera)

    print("Opening webcam. Press 'q' to quit.")

    liveness_detector = BlinkLivenessDetector(
        ear_threshold=args.threshold,
        required_blinks=args.required_blinks,
        min_closed_frames=args.min_blink_frames,
        max_closed_frames=args.max_blink_frames,
        challenge_seconds=args.liveness_timeout,
        head_movement_ratio=args.head_movement_threshold,
    )

    frame_index = 0
    last_face_locations: list[tuple[int, int, int, int]] = []
    last_faces_landmarks: list[Landmarks] = []
    last_liveness = None

    try:
        while True:
            ok, frame = camera.read()
            if not ok:
                raise RuntimeError("Could not read from webcam.")

            # Optimization: only every alternate frame does expensive liveness
            # work; skipped frames reuse the last result to keep video smooth.
            process_current_frame = frame_index % DEFAULT_PROCESS_EVERY_N_FRAMES == 0
            frame_index += 1

            if process_current_frame:
                # Optimization: shrink each webcam frame to 25% before detection.
                rgb_frame = resize_for_recognition(frame, args.frame_scale)

                # Optimization: force HOG, which is faster than CNN for CPU webcams.
                detected_locations = find_face_locations(rgb_frame, DEFAULT_DETECTION_MODEL)

                # Optimization: liveness tracks one primary face and ignores extras.
                face_locations = limit_to_primary_face(detected_locations)
                faces_landmarks = (
                    find_face_landmarks(rgb_frame, face_locations) if face_locations else []
                )
                liveness = liveness_detector.update(
                    faces_landmarks,
                    face_locations,
                    rgb_frame.shape,
                    frame_weight=DEFAULT_PROCESS_EVERY_N_FRAMES,
                )

                last_face_locations = face_locations
                last_faces_landmarks = faces_landmarks
                last_liveness = liveness
            else:
                face_locations = last_face_locations
                faces_landmarks = last_faces_landmarks
                liveness = last_liveness

            # Optimization: draw every webcam frame, even when processing is
            # skipped, so the preview keeps repainting without visible stalls.
            for landmarks in faces_landmarks:
                left_eye = scale_points(landmarks["left_eye"], args.frame_scale)
                right_eye = scale_points(landmarks["right_eye"], args.frame_scale)

                draw_eye_landmarks(frame, left_eye)
                draw_eye_landmarks(frame, right_eye)

            if liveness is None:
                cv2.putText(
                    frame,
                    "Initializing camera",
                    (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (255, 255, 255),
                    2,
                )
            elif liveness.ear is not None:
                cv2.putText(
                    frame,
                    f"EAR: {liveness.ear:.2f}",
                    (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (255, 255, 0),
                    2,
                )

            if liveness is not None and liveness.blink_detected:
                cv2.putText(
                    frame,
                    "Blink Detected",
                    (10, 70),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.9,
                    (0, 0, 255),
                    2,
                )

            if liveness is not None:
                cv2.putText(
                    frame,
                    f"Blinks: {liveness.blink_count}/{args.required_blinks}",
                    (10, 110),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (255, 255, 255),
                    2,
                )

                cv2.putText(
                    frame,
                    "Real User" if liveness.is_live else "Fake / No Liveness",
                    (10, 150),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.8,
                    (0, 255, 0) if liveness.is_live else (0, 0, 255),
                    2,
                )

                cv2.putText(
                    frame,
                    "Head movement: OK" if liveness.head_moved else "Head movement: needed",
                    (10, 190),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (0, 255, 0) if liveness.head_moved else (255, 255, 255),
                    2,
                )

                cv2.putText(
                    frame,
                    f"Time left: {liveness.time_remaining:.1f}s",
                    (10, 230),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (255, 255, 255),
                    2,
                )

                if liveness.timed_out:
                    cv2.putText(
                        frame,
                        "Liveness timeout - try again",
                        (10, 270),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.7,
                        (0, 0, 255),
                        2,
                    )

            cv2.imshow("Eye Blink Detection", frame)

            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        camera.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()

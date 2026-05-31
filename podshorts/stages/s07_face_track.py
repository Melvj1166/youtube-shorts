from __future__ import annotations

import numpy as np

import cv2
import mediapipe as mp
from filterpy.kalman import KalmanFilter

from podshorts.types import Context, FaceTrackInput, FaceTrackOutput, FrameCrop


def _make_kalman(cx: float, cy: float) -> KalmanFilter:
    kf = KalmanFilter(dim_x=4, dim_z=2)
    kf.x = np.array([[cx], [cy], [0.0], [0.0]])
    kf.F = np.array(
        [[1, 0, 1, 0], [0, 1, 0, 1], [0, 0, 1, 0], [0, 0, 0, 1]], dtype=float
    )
    kf.H = np.array([[1, 0, 0, 0], [0, 1, 0, 0]], dtype=float)
    kf.P *= 1000.0
    kf.R = np.eye(2) * 50.0
    kf.Q = np.eye(4) * 0.1
    return kf


def _bbox_area(detection, frame_w: int, frame_h: int) -> float:
    bbox = detection.location_data.relative_bounding_box
    return (bbox.width * frame_w) * (bbox.height * frame_h)


def _bbox_center(detection, frame_w: int, frame_h: int) -> tuple[float, float]:
    bbox = detection.location_data.relative_bounding_box
    cx = (bbox.xmin + bbox.width / 2.0) * frame_w
    cy = (bbox.ymin + bbox.height / 2.0) * frame_h
    return cx, cy


def run(input: FaceTrackInput, ctx: Context) -> FaceTrackOutput:
    logger = ctx.logger
    output = FaceTrackOutput()

    cap = cv2.VideoCapture(str(input.video_path))
    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        frame_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        frame_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        mp_face = mp.solutions.face_detection

        for scored_seg in input.segments:
            seg = scored_seg.segment
            seg_id = seg.segment_id

            start_frame = int(seg.start * fps)
            end_frame = min(int(seg.end * fps), total_frames - 1)
            n_frames = max(0, end_frame - start_frame + 1)

            if n_frames == 0:
                logger.info(
                    "Face tracking segment %s: 0 frames, skipping", seg_id
                )
                output.tracks[seg_id] = []
                continue

            # Collect raw detections first to find first detected face for KF init
            # Then do a second pass with Kalman.  To avoid double-seeking, collect
            # all frames and detections in memory.
            cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

            frames: list[np.ndarray] = []
            for _ in range(n_frames):
                ret, frame = cap.read()
                if not ret:
                    break
                frames.append(frame)

            # Run MediaPipe once per segment
            detections: list[tuple[float, float] | None] = []
            with mp_face.FaceDetection(
                model_selection=0, min_detection_confidence=0.5
            ) as detector:
                for frame in frames:
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    results = detector.process(rgb)

                    if results.detections:
                        if (
                            ctx.config.enable_diarization
                            and len(results.detections) > 1
                        ):
                            # With diarization enabled and multiple faces, pick the
                            # largest face as best-effort active-speaker proxy
                            # (no word-level speaker data in FaceTrackInput).
                            best = max(
                                results.detections,
                                key=lambda d: _bbox_area(d, frame_w, frame_h),
                            )
                        else:
                            best = max(
                                results.detections,
                                key=lambda d: _bbox_area(d, frame_w, frame_h),
                            )
                        cx, cy = _bbox_center(best, frame_w, frame_h)
                        detections.append((cx, cy))
                    else:
                        detections.append(None)

            n_detected = sum(1 for d in detections if d is not None)
            logger.info(
                "Face tracking segment %s: %d frames, %d detections",
                seg_id,
                len(frames),
                n_detected,
            )

            # Find first detection to initialise Kalman filter
            first_det = next((d for d in detections if d is not None), None)

            if first_det is None:
                # No faces found — use frame centre for all frames
                fallback_cx = frame_w / 2.0
                fallback_cy = frame_h / 2.0
                crops = [
                    FrameCrop(frame_idx=start_frame + i, cx=fallback_cx, cy=fallback_cy)
                    for i in range(len(frames))
                ]
                output.tracks[seg_id] = crops
                continue

            kf = _make_kalman(first_det[0], first_det[1])

            crops: list[FrameCrop] = []
            for i, det in enumerate(detections):
                frame_num = start_frame + i
                if det is not None:
                    cx, cy = det
                    kf.update(np.array([[cx], [cy]]))
                kf.predict()
                crops.append(
                    FrameCrop(
                        frame_idx=frame_num,
                        cx=float(kf.x[0, 0]),
                        cy=float(kf.x[1, 0]),
                    )
                )

            output.tracks[seg_id] = crops

    finally:
        cap.release()

    return output

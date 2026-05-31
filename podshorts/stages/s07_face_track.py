from __future__ import annotations

import numpy as np

import cv2
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


def _bbox_area(det) -> float:
    bb = det.bounding_box
    return float(bb.width * bb.height)


def _bbox_center(det) -> tuple[float, float]:
    bb = det.bounding_box
    return (bb.origin_x + bb.width / 2.0, bb.origin_y + bb.height / 2.0)


def _load_detector(model_path: str):
    from mediapipe.tasks.python.vision.face_detector import FaceDetector, FaceDetectorOptions
    from mediapipe.tasks.python.core.base_options import BaseOptions
    from mediapipe.tasks.python.vision.core.vision_task_running_mode import VisionTaskRunningMode

    options = FaceDetectorOptions(
        base_options=BaseOptions(model_asset_path=model_path),
        running_mode=VisionTaskRunningMode.IMAGE,
        min_detection_confidence=0.5,
    )
    return FaceDetector.create_from_options(options)


def _to_mp_image(frame_bgr):
    from mediapipe.tasks.python.vision.core.image import Image, ImageFormat
    rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
    return Image(image_format=ImageFormat.SRGB, data=rgb)


def run(input: FaceTrackInput, ctx: Context) -> FaceTrackOutput:
    logger = ctx.logger
    output = FaceTrackOutput()
    model_path = str(ctx.config.face_detector_model)

    cap = cv2.VideoCapture(str(input.video_path))
    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        frame_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        frame_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        for scored_seg in input.segments:
            seg = scored_seg.segment
            seg_id = seg.segment_id

            start_frame = int(seg.start * fps)
            end_frame = min(int(seg.end * fps), total_frames - 1)
            n_frames = max(0, end_frame - start_frame + 1)

            if n_frames == 0:
                logger.info("Face tracking segment %s: 0 frames, skipping", seg_id)
                output.tracks[seg_id] = []
                continue

            cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
            frames: list[np.ndarray] = []
            for _ in range(n_frames):
                ret, frame = cap.read()
                if not ret:
                    break
                frames.append(frame)

            detections: list[tuple[float, float] | None] = []
            detector = _load_detector(model_path)
            try:
                for frame in frames:
                    mp_img = _to_mp_image(frame)
                    result = detector.detect(mp_img)
                    if result.detections:
                        best = max(result.detections, key=_bbox_area)
                        detections.append(_bbox_center(best))
                    else:
                        detections.append(None)
            finally:
                detector.close()

            n_detected = sum(1 for d in detections if d is not None)
            logger.info(
                "Face tracking segment %s: %d frames, %d detections",
                seg_id, len(frames), n_detected,
            )

            first_det = next((d for d in detections if d is not None), None)

            if first_det is None:
                crops = [
                    FrameCrop(frame_idx=start_frame + i, cx=frame_w / 2.0, cy=frame_h / 2.0)
                    for i in range(len(frames))
                ]
                output.tracks[seg_id] = crops
                continue

            kf = _make_kalman(first_det[0], first_det[1])
            crops: list[FrameCrop] = []
            for i, det in enumerate(detections):
                if det is not None:
                    kf.update(np.array([[det[0]], [det[1]]]))
                kf.predict()
                crops.append(FrameCrop(
                    frame_idx=start_frame + i,
                    cx=float(kf.x[0, 0]),
                    cy=float(kf.x[1, 0]),
                ))
            output.tracks[seg_id] = crops

    finally:
        cap.release()

    return output

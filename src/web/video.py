"""MJPEG video streaming for the Web console."""

from __future__ import annotations

from dataclasses import dataclass
import threading
import time
from typing import Iterator

from src.config import WebConfig


@dataclass(frozen=True, slots=True)
class CameraKey:
    device: str
    width: int
    height: int
    fps: int
    jpeg_quality: int


_STREAMERS: dict[CameraKey, "SharedCameraStreamer"] = {}
_STREAMERS_LOCK = threading.Lock()
_CLIENT_IDLE_TIMEOUT_S = 5.0


class SharedCameraStreamer:
    """One camera reader shared by every MJPEG client."""

    def __init__(self, key: CameraKey) -> None:
        self._key = key
        self._condition = threading.Condition()
        self._thread: threading.Thread | None = None
        self._running = False
        self._stop_requested = False
        self._client_count = 0
        self._last_client_frame_at = time.monotonic()
        self._latest_frame: bytes | None = None
        self._latest_error: str | None = None
        self._frame_index = 0

    def start(self) -> None:
        with self._condition:
            if self._running:
                return
            self._running = True
            self._stop_requested = False
            self._thread = threading.Thread(target=self._run, name="ghost-web-camera", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        with self._condition:
            self._stop_requested = True
            self._condition.notify_all()
            thread = self._thread
        if thread is not None:
            thread.join(timeout=3.0)

    def frames(self) -> Iterator[bytes]:
        self._add_client()
        self.start()
        last_index = -1
        try:
            while True:
                with self._condition:
                    self._condition.wait_for(
                        lambda: (
                            self._frame_index != last_index
                            or self._latest_error is not None
                            or not self._running
                        ),
                        timeout=5.0,
                    )
                    if not self._running:
                        return
                    if self._latest_error is not None and self._latest_frame is None:
                        raise RuntimeError(self._latest_error)
                    if self._latest_frame is None or self._frame_index == last_index:
                        continue
                    last_index = self._frame_index
                    payload = self._latest_frame
                    self._last_client_frame_at = time.monotonic()
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n"
                    b"Content-Length: " + str(len(payload)).encode("ascii") + b"\r\n\r\n" + payload + b"\r\n"
                )
        finally:
            self._remove_client()

    def _run(self) -> None:
        try:
            import cv2
        except ImportError:
            self._set_error("OpenCV is required for /api/video.mjpg.")
            return

        device: int | str = self._key.device
        if isinstance(device, str) and device.isdigit():
            device = int(device)

        frame_delay = 1.0 / max(1, self._key.fps)
        encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), int(self._key.jpeg_quality)]

        try:
            while not self._stop_requested:
                capture = cv2.VideoCapture(device)
                if not capture.isOpened():
                    self._set_error(f"Could not open video device {self._key.device!r}.")
                    self._sleep_or_stop(1.0)
                    continue

                self._latest_error = None
                try:
                    capture.set(cv2.CAP_PROP_FRAME_WIDTH, self._key.width)
                    capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self._key.height)
                    capture.set(cv2.CAP_PROP_FPS, self._key.fps)
                    while not self._stop_requested:
                        if self._client_stream_is_stale():
                            break
                        ok, frame = capture.read()
                        if not ok:
                            self._set_error("Camera read returned no frame.")
                            self._sleep_or_stop(frame_delay)
                            continue
                        encoded, buffer = cv2.imencode(".jpg", frame, encode_params)
                        if not encoded:
                            self._set_error("Camera frame could not be JPEG-encoded.")
                            self._sleep_or_stop(frame_delay)
                            continue
                        with self._condition:
                            self._latest_error = None
                            self._latest_frame = buffer.tobytes()
                            self._frame_index += 1
                            self._condition.notify_all()
                        self._sleep_or_stop(frame_delay)
                finally:
                    capture.release()
        finally:
            with self._condition:
                self._running = False
                self._thread = None
                self._condition.notify_all()

    def _set_error(self, message: str) -> None:
        with self._condition:
            self._latest_error = message
            self._condition.notify_all()

    def _sleep_or_stop(self, seconds: float) -> None:
        deadline = time.monotonic() + seconds
        while not self._stop_requested and time.monotonic() < deadline:
            time.sleep(min(0.05, deadline - time.monotonic()))

    def _add_client(self) -> None:
        with self._condition:
            self._client_count += 1
            self._last_client_frame_at = time.monotonic()

    def _remove_client(self) -> None:
        should_stop = False
        with self._condition:
            if self._client_count > 0:
                self._client_count -= 1
            should_stop = self._client_count == 0 and self._running
        if should_stop:
            self.stop()

    def _client_stream_is_stale(self) -> bool:
        with self._condition:
            if self._client_count <= 0:
                return True
            if time.monotonic() - self._last_client_frame_at <= _CLIENT_IDLE_TIMEOUT_S:
                return False
            self._client_count = 0
            self._stop_requested = True
            self._condition.notify_all()
            return True


def mjpeg_frames(config: WebConfig) -> Iterator[bytes]:
    """Yield multipart MJPEG frames from a shared camera reader."""

    key = CameraKey(
        device=config.video_device,
        width=config.video_width,
        height=config.video_height,
        fps=config.video_fps,
        jpeg_quality=config.video_jpeg_quality,
    )
    with _STREAMERS_LOCK:
        streamer = _STREAMERS.get(key)
        if streamer is None:
            streamer = SharedCameraStreamer(key)
            _STREAMERS[key] = streamer
    return streamer.frames()


def stop_all_camera_streamers() -> None:
    """Release camera devices before an exclusive GhostVision capture."""

    with _STREAMERS_LOCK:
        streamers = list(_STREAMERS.values())
        _STREAMERS.clear()
    for streamer in streamers:
        streamer.stop()

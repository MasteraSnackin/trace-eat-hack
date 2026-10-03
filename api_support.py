"""Bounded local API inputs and diagnostics that exclude camera data."""
import asyncio
import logging
import traceback

import cv2
import numpy as np
from fastapi import HTTPException, Request
from starlette.requests import ClientDisconnect

MAX_IMAGE_BYTES = 2_000_000
MAX_CONFIG_BYTES = 16_384
UPLOAD_TIMEOUT_S = 5
INFERENCE_TIMEOUT_S = 15
LOGGER = logging.getLogger("trace.api")


class ApiError(HTTPException):
    def __init__(self, status: int, code: str, detail: str):
        super().__init__(status, detail)
        self.code = code


def log_failure(context: str, error: Exception, request_id: str):
    # Record stack locations, but never the exception text, local variables or
    # request body. Native errors can contain machine paths or model contents.
    frames = traceback.extract_tb(error.__traceback__)
    locations = " <- ".join(f"{frame.name}:{frame.lineno}" for frame in frames)
    LOGGER.error("%s request_id=%s error=%s stack=%s",
                 context, request_id, type(error).__name__, locations)


async def read_body(request: Request, limit: int, limit_message: str) -> bytearray:
    declared = request.headers.get("content-length")
    if declared is not None:
        if not declared.isascii() or not declared.isdigit():
            raise ApiError(400, "invalid_content_length", "The request length is invalid.")
        # Compare the string length first to avoid parsing an unbounded integer.
        if len(declared) > 10 or int(declared) > limit:
            raise ApiError(413, "body_too_large", limit_message)
    body = bytearray()
    try:
        async with asyncio.timeout(UPLOAD_TIMEOUT_S):
            async for chunk in request.stream():
                if len(body) + len(chunk) > limit:
                    raise ApiError(413, "body_too_large", limit_message)
                body.extend(chunk)
    except TimeoutError:
        raise ApiError(408, "upload_timeout", "The upload took too long. Try again.") from None
    except ClientDisconnect:
        raise ApiError(400, "client_disconnected", "The request ended before the upload finished.") from None
    if declared is not None and int(declared) != len(body):
        raise ApiError(400, "invalid_content_length", "The request length does not match its body.")
    return body


def jpeg_dimensions(body: bytes | bytearray) -> tuple[int, int]:
    """Read JPEG SOF dimensions before allowing a native decoder allocation."""
    if not body.startswith(b"\xff\xd8") or not body.endswith(b"\xff\xd9"):
        raise ApiError(422, "invalid_frame", "Invalid JPEG camera frame.")
    offset = 2
    # JPEG frame markers exclude DHT (C4), JPG (C8) and DAC (CC).
    frame_markers = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                     0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
    while offset < len(body):
        if body[offset] != 0xFF:
            break
        while offset < len(body) and body[offset] == 0xFF:
            offset += 1
        if offset >= len(body):
            break
        marker = body[offset]
        offset += 1
        if marker in {0x00, 0xD8, 0xD9, 0xDA}:
            break
        if marker == 0x01 or 0xD0 <= marker <= 0xD7:
            continue
        if offset + 2 > len(body):
            break
        length = int.from_bytes(body[offset:offset + 2], "big")
        if length < 2 or offset + length > len(body):
            break
        if marker in frame_markers:
            if length < 8:
                break
            height = int.from_bytes(body[offset + 3:offset + 5], "big")
            width = int.from_bytes(body[offset + 5:offset + 7], "big")
            if min(width, height) < 120 or max(width, height) > 1920:
                raise ApiError(422, "invalid_frame_size",
                               "Use a JPEG frame between 120 and 1920 pixels per side.")
            return width, height
        offset += length
    raise ApiError(422, "invalid_frame", "Invalid JPEG camera frame.")


def decode_frame(body: bytearray) -> np.ndarray:
    width, height = jpeg_dimensions(body)
    try:
        frame = cv2.imdecode(np.frombuffer(body, dtype=np.uint8), cv2.IMREAD_COLOR)
    except cv2.error:
        raise ApiError(422, "invalid_frame", "The JPEG frame could not be decoded. Try the camera again.") from None
    if frame is None or frame.shape[:2] != (height, width):
        raise ApiError(422, "invalid_frame", "The JPEG frame could not be decoded. Try the camera again.")
    return frame

"""Transport and request rules for the Seedance 2.5 MCP adapter.

This module deliberately uses urllib so the MCP repository has no hidden SDK
or import-time network side effect. It is also easy to exercise with a local
opener in tests.
"""
from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

BASE_URL = "https://argolink.io/v1"
MODEL = "seedance-2.5"
USER_AGENT = "seedance-2-5-video-mcp/1.0"
STATUSES = {"pending", "done", "failed", "expired"}
RATIOS = {"21:9", "16:9", "4:3", "1:1", "3:4", "9:16"}
RESOLUTIONS = {"480p", "720p", "1080p"}
REQUEST_ID = re.compile(r"^[A-Za-z0-9_-]{1,160}$")
CONTENT_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".webm": "video/webm",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".m4a": "audio/mp4",
}
MAX_UPLOAD = {"image": 20 * 1024 * 1024, "video": 100 * 1024 * 1024, "audio": 15 * 1024 * 1024}


class VideoAPIError(RuntimeError):
    """An API or local contract error with a safe, actionable message."""

    def __init__(self, message: str, *, status: Optional[int] = None, body: Any = None) -> None:
        super().__init__(message)
        self.status = status
        self.body = body


def _https(value: str, field: str) -> str:
    if not isinstance(value, str) or urllib.parse.urlparse(value).scheme != "https":
        raise ValueError(f"{field} must be an https URL; upload local files first")
    if not urllib.parse.urlparse(value).netloc:
        raise ValueError(f"{field} must contain a host")
    return value


def _media(value: str, field: str) -> Dict[str, str]:
    return {"url": _https(value, field)}


def _list_urls(values: Iterable[str], field: str) -> List[Dict[str, str]]:
    return [_media(value, f"{field}[{index}]") for index, value in enumerate(values)]


def _require_duration(duration: Optional[int]) -> int:
    if isinstance(duration, bool) or not isinstance(duration, int) or not 4 <= duration <= 30:
        raise ValueError("duration must be a whole number from 4 through 30")
    return duration


def _require_prompt(prompt: str) -> str:
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("prompt is required in every Seedance 2.5 mode")
    if len(prompt.encode("utf-8")) > 40_000:
        raise ValueError("prompt exceeds the 40,000 UTF-8 byte limit")
    return prompt


class SeedanceClient:
    """A small authenticated client with no generation polling or auto-resubmit."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        *,
        base_url: Optional[str] = None,
        timeout: float = 90.0,
        opener: Optional[Callable[..., Any]] = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else os.environ.get("VIDEO_API_KEY")
        self.base_url = (base_url or os.environ.get("VIDEO_API_BASE_URL") or BASE_URL).rstrip("/")
        self.timeout = timeout
        self._open = opener or urllib.request.urlopen

    def _api_request(
        self, method: str, path: str, body: Optional[Dict[str, Any]] = None, *, binary: bool = False
    ) -> Any:
        if not self.api_key:
            raise VideoAPIError("VIDEO_API_KEY is required in the MCP host environment")
        if not path.startswith("/") or ".." in path:
            raise VideoAPIError("invalid API path")
        data = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8") if body is not None else None
        headers = {"Authorization": f"Bearer {self.api_key}", "User-Agent": USER_AGENT, "Accept": "*/*"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(self.base_url + path, data=data, method=method, headers=headers)
        try:
            response = self._open(request, timeout=self.timeout)
        except urllib.error.HTTPError as error:
            raw = error.read(4096).decode("utf-8", errors="replace")
            try:
                detail = json.loads(raw)
            except ValueError:
                detail = raw
            message = detail.get("error", {}).get("message") if isinstance(detail, dict) else None
            raise VideoAPIError(
                f"{method} {path} returned HTTP {error.code}: {message or raw[:300] or error.reason}",
                status=error.code,
                body=detail,
            ) from None
        try:
            raw = response.read()
        finally:
            response.close()
        if binary:
            return raw
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise VideoAPIError(f"{method} {path} returned invalid JSON") from error
        if not isinstance(payload, dict):
            raise VideoAPIError(f"{method} {path} returned a non-object response")
        return payload

    def build_request(
        self,
        *,
        prompt: str,
        mode: str,
        duration: Optional[int],
        resolution: str,
        aspect_ratio: Optional[str],
        generate_audio: bool,
        start_image: Optional[str],
        end_image: Optional[str],
        reference_images: List[str],
        reference_videos: List[str],
        reference_audios: List[str],
        edit_video: Optional[str],
    ) -> Dict[str, Any]:
        _require_prompt(prompt)
        if resolution not in RESOLUTIONS:
            raise ValueError("resolution must be 480p, 720p, or 1080p")
        valid_modes = {"text", "start_image", "first_last_frames", "multimodal_reference", "video_edit"}
        if mode not in valid_modes:
            raise ValueError("mode must be text, start_image, first_last_frames, multimodal_reference, or video_edit")
        if not isinstance(generate_audio, bool):
            raise ValueError("generate_audio must be boolean")
        lists = (reference_images, reference_videos, reference_audios)
        if any(not isinstance(values, list) for values in lists):
            raise ValueError("reference collections must be lists")
        if len(reference_images) > 30 or len(reference_videos) > 10 or len(reference_audios) > 10:
            raise ValueError("reference limits are 30 images, 10 videos, and 10 audio clips")
        if sum(map(len, lists)) > 50:
            raise ValueError("at most 50 reference assets can be sent")
        if mode in {"start_image", "first_last_frames"}:
            if not start_image:
                raise ValueError("start_image is required for a frame request")
            if mode == "start_image" and end_image:
                raise ValueError("start_image mode cannot include end_image")
            if mode == "first_last_frames" and not end_image:
                raise ValueError("first_last_frames requires end_image")
            if any(lists) or edit_video:
                raise ValueError("frame requests cannot combine references or edit_video")
            result = {
                "model": MODEL,
                "prompt": prompt,
                "duration": _require_duration(duration),
                "resolution": resolution,
                "aspect_ratio": "adaptive",
                "generate_audio": generate_audio,
                "start_image": _media(start_image, "start_image"),
            }
            if end_image:
                result["end_image"] = _media(end_image, "end_image")
            return result
        if mode == "video_edit":
            if not edit_video:
                raise ValueError("video_edit requires edit_video")
            if start_image or end_image or reference_images or reference_audios or reference_videos:
                raise ValueError("video_edit accepts only edit_video as its input asset")
            return {
                "model": MODEL,
                "prompt": prompt,
                "resolution": resolution,
                "generate_audio": generate_audio,
                "omni_reference_task_type": "edit",
                "reference_videos": [_media(edit_video, "edit_video")],
            }
        if start_image or end_image or edit_video:
            raise ValueError("text and multimodal_reference use their named reference fields only")
        body: Dict[str, Any] = {
            "model": MODEL,
            "prompt": prompt,
            "duration": _require_duration(duration),
            "resolution": resolution,
            "aspect_ratio": aspect_ratio or "16:9",
            "generate_audio": generate_audio,
        }
        if mode == "text":
            if any(lists):
                raise ValueError("text mode cannot include reference assets")
            if body["aspect_ratio"] not in RATIOS:
                raise ValueError("text aspect_ratio must be one of the six fixed ratios")
            return body
        if not any(lists):
            raise ValueError("multimodal_reference requires at least one reference asset")
        if body["aspect_ratio"] not in RATIOS:
            raise ValueError("reference aspect_ratio must be one of the six fixed ratios")
        if reference_images:
            body["reference_images"] = _list_urls(reference_images, "reference_images")
        if reference_videos:
            body["reference_videos"] = _list_urls(reference_videos, "reference_videos")
        if reference_audios:
            body["reference_audios"] = _list_urls(reference_audios, "reference_audios")
        return body

    def submit(self, body: Dict[str, Any]) -> Dict[str, Any]:
        response = self._api_request("POST", "/videos/generations", body)
        request_id = response.get("request_id")
        if not isinstance(request_id, str) or not REQUEST_ID.fullmatch(request_id):
            raise VideoAPIError("generation response did not contain a valid request_id", body=response)
        return {"request_id": request_id, "status": response.get("status", "pending"), "response": response}

    def _check_id(self, request_id: str) -> str:
        if not isinstance(request_id, str) or not REQUEST_ID.fullmatch(request_id):
            raise ValueError("request_id must contain only letters, numbers, underscore, or hyphen")
        return request_id

    def status(self, request_id: str) -> Dict[str, Any]:
        return self._api_request("GET", "/videos/" + self._check_id(request_id))

    def _root(self) -> Path:
        raw = os.environ.get("VIDEO_MCP_MEDIA_ROOT")
        if not raw:
            raise VideoAPIError("set VIDEO_MCP_MEDIA_ROOT to a dedicated media directory")
        root = Path(raw).expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _safe_path(self, value: str, *, existing: bool) -> Path:
        if not isinstance(value, str) or not value:
            raise ValueError("a media path is required")
        root = self._root()
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = root / path
        path = path.resolve(strict=existing)
        try:
            path.relative_to(root)
        except ValueError:
            raise ValueError("media paths must stay under VIDEO_MCP_MEDIA_ROOT") from None
        return path

    def upload(self, file_path: str, content_type: Optional[str] = None) -> Dict[str, Any]:
        source = self._safe_path(file_path, existing=True)
        if not source.is_file():
            raise ValueError("file_path must be a regular file")
        guessed = content_type or CONTENT_TYPES.get(source.suffix.lower()) or mimetypes.guess_type(source.name)[0]
        if not guessed or "/" not in guessed:
            raise ValueError("content_type must identify image, video, or audio media")
        kind = guessed.split("/", 1)[0]
        if kind not in MAX_UPLOAD:
            raise ValueError("only image, video, and audio uploads are supported")
        size = source.stat().st_size
        if size > MAX_UPLOAD[kind]:
            raise ValueError(f"{kind} upload exceeds the {MAX_UPLOAD[kind] // (1024 * 1024)} MiB limit")
        ticket = self._api_request("POST", "/media/uploads", {
            "model": MODEL, "type": kind, "content_type": guessed, "size_bytes": size,
        })
        upload_url = ticket.get("upload_url")
        media_url = ticket.get("media_url")
        if not isinstance(upload_url, str) or urllib.parse.urlparse(upload_url).scheme != "https":
            raise VideoAPIError("upload ticket did not return an https upload_url", body=ticket)
        if not isinstance(media_url, str) or urllib.parse.urlparse(media_url).scheme != "https":
            raise VideoAPIError("upload ticket did not return an https media_url", body=ticket)
        request = urllib.request.Request(
            upload_url, data=source.read_bytes(), method="PUT",
            headers={"Content-Type": guessed, "User-Agent": USER_AGENT},
        )
        try:
            response = self._open(request, timeout=max(self.timeout, 300.0))
            response.close()
        except urllib.error.HTTPError as error:
            raise VideoAPIError(f"media upload returned HTTP {error.code}", status=error.code) from None
        return {"media_url": media_url, "content_type": guessed, "bytes": size}

    def download(self, request_id: str, output_path: str) -> Dict[str, Any]:
        request_id = self._check_id(request_id)
        state = self.status(request_id).get("status")
        if state != "done":
            raise VideoAPIError(f"request {request_id} is {state!r}; content is available only after done")
        target = self._safe_path(output_path, existing=False)
        if target.exists():
            raise FileExistsError(str(target))
        target.parent.mkdir(parents=True, exist_ok=True)
        response = None
        temporary = None
        try:
            # Keep the partial file out of the destination and publish by a
            # hard-link, which fails instead of replacing a concurrent output.
            response = self._api_request("GET", f"/videos/{request_id}/content", binary=True)
            with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".download-", delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(response)
                handle.flush()
                os.fsync(handle.fileno())
            os.link(temporary, target)
            temporary.unlink()
            temporary = None
        finally:
            if temporary and temporary.exists():
                temporary.unlink()
        return {"request_id": request_id, "path": str(target), "bytes": target.stat().st_size}

"""A stdio MCP adapter for the Seedance 2.5 video contract.

The MCP layer only translates typed tool arguments. HTTP, request validation,
upload safety and atomic file handling live in seedance_client so the same
rules are exercised by tests and by every tool.
"""
from __future__ import annotations

from typing import List, Optional

from mcp.server.fastmcp import FastMCP

from seedance_client import SeedanceClient


mcp = FastMCP(
    "seedance-2-5-video",
    instructions=(
        "Submit one Seedance 2.5 request, inspect its status, and download its "
        "completed MP4. Upload media first when a local file is needed. "
        "The server never polls or retries a generation implicitly."
    ),
)
client = SeedanceClient()


@mcp.tool()
def submit_video(
    prompt: str,
    mode: str = "text",
    duration: Optional[int] = 5,
    resolution: str = "720p",
    aspect_ratio: Optional[str] = "16:9",
    generate_audio: bool = True,
    start_image: Optional[str] = None,
    end_image: Optional[str] = None,
    reference_images: Optional[List[str]] = None,
    reference_videos: Optional[List[str]] = None,
    reference_audios: Optional[List[str]] = None,
    edit_video: Optional[str] = None,
) -> dict:
    """Submit text, frame, reference, or edit mode and return its request_id.

    Media values are public HTTPS URLs. For local files, call upload_media first.
    mode is one of text, start_image, first_last_frames,
    multimodal_reference, or video_edit.
    """
    body = client.build_request(
        prompt=prompt,
        mode=mode,
        duration=duration,
        resolution=resolution,
        aspect_ratio=aspect_ratio,
        generate_audio=generate_audio,
        start_image=start_image,
        end_image=end_image,
        reference_images=reference_images or [],
        reference_videos=reference_videos or [],
        reference_audios=reference_audios or [],
        edit_video=edit_video,
    )
    return client.submit(body)


@mcp.tool()
def get_video_status(request_id: str) -> dict:
    """Read one request; statuses are pending, done, failed, or expired."""
    return client.status(request_id)


@mcp.tool()
def download_video(request_id: str, output_path: str) -> dict:
    """Download a completed MP4 to a new file under VIDEO_MCP_MEDIA_ROOT."""
    return client.download(request_id, output_path)


@mcp.tool()
def upload_media(file_path: str, content_type: Optional[str] = None) -> dict:
    """Request an upload ticket and PUT a local image, video, or audio file.

    The key is sent only to the API ticket endpoint; it is never sent to the
    presigned storage URL. Files must be under VIDEO_MCP_MEDIA_ROOT.
    """
    return client.upload(file_path, content_type)


if __name__ == "__main__":
    mcp.run(transport="stdio")

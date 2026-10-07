# Seedance 2.5 video MCP server

A focused Model Context Protocol server for generating Seedance 2.5 video through an OpenAI-compatible HTTPS API. It exposes four useful tools: submit a request, read one request status, upload local media, and download the finished MP4. The adapter does not run a hidden polling loop and never resubmits a request after a timeout.

[Open the Seedance 2.5 model page](https://argolink.io/en/models/seedance-2.5) for the current model contract, live availability, and a browser-based request example.

## What this server does

The server is a small stdio process. The MCP host starts it and exchanges JSON-RPC messages over stdin/stdout. The process sends authenticated requests to:

| Operation | HTTP request | Result |
| --- | --- | --- |
| Submit | POST https://argolink.io/v1/videos/generations | A request_id and pending job |
| Status | GET https://argolink.io/v1/videos/{request_id} | pending, done, failed, or expired |
| Content | GET https://argolink.io/v1/videos/{request_id}/content | The completed MP4 |
| Upload ticket | POST https://argolink.io/v1/media/uploads | A short-lived upload URL and media URL |
| Upload bytes | PUT to the ticket URL | No API bearer token is sent to storage |

Every API request includes a descriptive User-Agent. The API key is read from the MCP host environment and is never stored in this repository. Presigned upload requests deliberately contain only Content-Type and User-Agent.

## Install

Python 3.10 or newer is recommended.

~~~sh
git clone https://github.com/YOUR_ACCOUNT/seedance-2-5-video-mcp
cd seedance-2-5-video-mcp
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
export VIDEO_API_KEY='replace-in-your-secret-store'
export VIDEO_MCP_MEDIA_ROOT="$PWD/media"
mkdir -p "$VIDEO_MCP_MEDIA_ROOT"
python server.py
~~~

The last command is normally run by an MCP host rather than by hand. Use a dedicated media directory. VIDEO_MCP_MEDIA_ROOT is required for both upload and download so a model cannot use the tool to read or overwrite arbitrary files in the operator's home directory. A download refuses to replace an existing file and publishes a completed file atomically.

For a compatible local test server, set VIDEO_API_BASE_URL to its HTTPS or local test URL. The default is https://argolink.io/v1.

## MCP host configuration

Use an absolute path to the virtual-environment interpreter and server.py. Keep the real key outside the checked-in JSON. The examples use a placeholder intentionally.

### Claude Desktop

On macOS the file is ~/Library/Application Support/Claude/claude_desktop_config.json; on Windows it is %APPDATA%/Claude/claude_desktop_config.json.

~~~json
{
  "mcpServers": {
    "seedance-2-5-video": {
      "command": "/absolute/path/seedance-2-5-video-mcp/.venv/bin/python",
      "args": ["/absolute/path/seedance-2-5-video-mcp/server.py"],
      "env": {
        "VIDEO_API_KEY": "REPLACE_LOCALLY",
        "VIDEO_MCP_MEDIA_ROOT": "/absolute/path/seedance-2-5-video-mcp/media"
      }
    }
  }
}
~~~

Replace the placeholder locally and keep the file private. Restart Claude Desktop after changing the file.

### Claude Code

The project .mcp.json format supports environment interpolation:

~~~json
{
  "mcpServers": {
    "seedance-2-5-video": {
      "type": "stdio",
      "command": "/absolute/path/seedance-2-5-video-mcp/.venv/bin/python",
      "args": ["/absolute/path/seedance-2-5-video-mcp/server.py"],
      "env": {
        "VIDEO_API_KEY": "\${VIDEO_API_KEY}",
        "VIDEO_MCP_MEDIA_ROOT": "/absolute/path/seedance-2-5-video-mcp/media"
      }
    }
  }
}
~~~

Or add the same command with claude mcp add --transport stdio and set the variables in the shell that launches Claude Code.

### Cursor

Cursor's project or global MCP JSON uses the stdio type. Its current configuration supports environment interpolation and an envFile for stdio servers:

~~~json
{
  "mcpServers": {
    "seedance-2-5-video": {
      "type": "stdio",
      "command": "/absolute/path/seedance-2-5-video-mcp/.venv/bin/python",
      "args": ["/absolute/path/seedance-2-5-video-mcp/server.py"],
      "env": {
        "VIDEO_API_KEY": "\${env:VIDEO_API_KEY}",
        "VIDEO_MCP_MEDIA_ROOT": "/absolute/path/seedance-2-5-video-mcp/media"
      },
      "envFile": "/absolute/private/seedance.env"
    }
  }
}
~~~

Use the host's current settings UI and configuration documentation when the location differs between releases.

## Tool reference

### submit_video

Arguments:

| Argument | Values and meaning |
| --- | --- |
| prompt | Required UTF-8 text, at most 40,000 bytes |
| mode | text, start_image, first_last_frames, multimodal_reference, or video_edit |
| duration | Integer 4 through 30 for every mode except edit |
| resolution | 480p, 720p, or 1080p |
| aspect_ratio | Six fixed ratios for text and references |
| generate_audio | Boolean; true by default |
| start_image, end_image | HTTPS media URLs for frame modes |
| reference_images, reference_videos, reference_audios | HTTPS URL lists for reference mode |
| edit_video | One HTTPS video URL for edit mode |

Frame modes force aspect_ratio to adaptive. A first-and-last-frame request requires both URLs. Reference mode allows up to 30 images, 10 videos, and 10 audio tracks, with 50 assets total; audio-only reference input is valid. A reference video or audio clip is 2 to 30 seconds, and the combined seconds of each media type cannot exceed 30. The API checks those media durations after it receives the URLs, while this adapter checks the count and URL scheme before sending.

Video edit uses omni_reference_task_type: edit and one reference_videos entry. It intentionally omits duration and aspect ratio because the result follows the source clip. Edits accept one 4–30 second source video.

### get_video_status

Pass the returned request_id and call this tool whenever the host wants to poll. The adapter returns the API object without pretending that pending is complete. failed and expired are terminal; investigate the error object before submitting another billable request.

### upload_media

Pass a path under VIDEO_MCP_MEDIA_ROOT. The tool infers common JPEG, PNG, WebP, MP4, MOV, WebM, MP3, WAV, and M4A types, or accepts content_type explicitly. Image uploads are limited to 20 MiB, video to 100 MiB, and audio to 15 MiB. Use the returned media_url in submit_video.

### download_video

Pass a completed request_id and a new path under the media root. The tool reads status first, requests /content only for done, writes a temporary file, fsyncs it, and atomically links it into place. It will not overwrite an existing output.

## Runnable HTTP example

This is the same lifecycle without MCP. It sends one request, saves the ID, polls explicitly, and downloads only after done.

~~~sh
BASE=https://argolink.io/v1
AUTH="Authorization: Bearer $VIDEO_API_KEY"
JOB=$(curl --fail-with-body -sS "$BASE/videos/generations" \
  -H "$AUTH" -H "User-Agent: seedance-2-5-video-mcp/1.0" \
  -H 'Content-Type: application/json' \
  -d '{"model":"seedance-2.5","prompt":"A paper kite crosses a sunset city skyline","duration":5,"resolution":"720p","aspect_ratio":"16:9","generate_audio":true}')
ID=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["request_id"])' <<< "$JOB")
while :; do
  STATE=$(curl --fail-with-body -sS "$BASE/videos/$ID" -H "$AUTH" -H 'User-Agent: seedance-2-5-video-mcp/1.0')
  STATUS=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["status"])' <<< "$STATE")
  case "$STATUS" in
    done) break ;;
    failed|expired) printf '%s\n' "$STATE" >&2; exit 1 ;;
    pending) sleep 10 ;;
    *) printf 'unexpected status: %s\n' "$STATUS" >&2; exit 1 ;;
  esac
done
curl --fail-with-body -sS "$BASE/videos/$ID/content" -H "$AUTH" \
  -H 'User-Agent: seedance-2-5-video-mcp/1.0' -o media/skyline.mp4
~~~

Never place a real bearer token in a shell history, README, issue, or MCP configuration committed to Git.

## Model limits and pricing

These values were checked against the live model catalog and model page on 2026-10-07; the model page is authoritative when they change.

| Capability | Seedance 2.5 |
| --- | --- |
| Output | One 24 fps H.264 MP4 with AAC stereo audio unless audio is disabled |
| Duration | 4–30 seconds; edit follows a 4–30 second source |
| Resolution | 480p, 720p, 1080p |
| Text/reference ratios | 21:9, 16:9, 4:3, 1:1, 3:4, 9:16 |
| Frame ratio | adaptive |
| Prompt | 40,000 UTF-8 bytes |
| References | 30 images, 10 videos, 10 audio tracks, 50 total |
| Reference media | 2–30 seconds each; 30 seconds total per video/audio type |
| Outputs per request | exactly one |

The effective rates currently shown for this endpoint are 0.0874 USD/s at 480p, 0.196 USD/s at 720p, and 0.483 USD/s at 1080p. A five-second 720p generation therefore estimates 0.98 USD before any reference-video seconds. The official catalog rate is 0.1028, 0.2311, and 0.5686 USD/s respectively. Reference video seconds are billed in addition to output seconds. Failed, rejected, and expired jobs are not charged under the model contract.

For comparison, [Evolink's Seedance 2.5 page](https://evolink.ai/seedance-2-5) currently publishes per-output-second tiers around 0.138/0.296/0.739 USD for 480p/720p/1080p, while [fal.ai's Seedance 2.5 page](https://fal.ai/models/bytedance/seedance-2.5/text-to-video) describes token-based pricing and a 720p example. Those pages are useful comparison points, but their request fields and billing formulas are not interchangeable with this API.

## Errors and operational behavior

The API can return 400 for invalid fields, 401 for missing or invalid credentials, 402 for billing or balance problems, 404 for an unknown request ID, 409 when content is not ready, 424 when a job failed, 429 for rate limiting, and 503 for temporary service unavailability. Preserve the response body and request ID when reporting an error. A timeout after POST is ambiguous: check status before retrying, because automatic resubmission could create a second job.

The server sends Retry-After information back as an API error when present, but it does not sleep and it does not repeat a generation. This keeps MCP calls bounded and makes the request ID recoverable by the host.

## Development

~~~sh
python -m unittest discover -s tests -v
python -m py_compile server.py seedance_client.py
~~~

The tests use a local fake opener and never call the production API. A real generation requires the operator's own key and is intentionally not part of automated tests.

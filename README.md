# Seedance 2.5 API — MCP video tools from $0.0874/s

**ByteDance Seedance 2.5 is available on [ArgoLink](https://argolink.io/gh-seedance-2-5-video-mcp).** This repository is an independent, stdio-only MCP server exposing submit, status, and media tools. It is not affiliated with ByteDance or the MCP project. Last checked: 2026-10-07.

## Install

python3 -m venv .venv && . .venv/bin/activate
python -m pip install "mcp>=1.0,<2"
export VIDEO_API_KEY="your-key"

The default base URL is https://argolink.io/v1; set VIDEO_API_BASE_URL for a compatible test server. Every request includes a descriptive User-Agent. No key is in this repository or its MCP JSON.

## Configure a host

Claude Desktop configuration uses a server entry with command, args, and env. For Claude Code, use claude mcp add --transport stdio seedance-video --env VIDEO_API_KEY=$VIDEO_API_KEY -- /absolute/.venv/bin/python /absolute/server.py. Cursor uses its MCP settings JSON with the same command/args/env shape. Keep the key in the host secret store and verify the host's current settings UI before copying configuration.

## Tools and lifecycle

| Tool | Arguments | Behavior |
|---|---|---|
| submit_video | prompt, duration, resolution, aspect_ratio, generate_audio | One POST; validates model and duration |
| get_video_status | request_id | GET; returns pending, done, failed, or expired |
| get_video_media | request_id, optional output_path | Requires done, then downloads MP4 |

The server has no hidden polling loop: the MCP client chooses an interval and can resume with a saved ID. If a POST times out after the provider may have accepted it, investigate the ID before submitting again. Failed or expired jobs are not charged under the service contract. Content before completion returns 409; failed content returns 424.

## Model boundary and price

Seedance 2.5 accepts 4–30 seconds and 480p/720p/1080p; prompt and reference limits belong to its live model page. First/last-frame requests require the documented adaptive ratio. This minimal tool covers text-to-video; add reference uploads only after reviewing the current contract.

Checked effective rates are $0.0874/s (480p), $0.196/s (720p), and $0.483/s (1080p). A five-second 720p sample estimates $0.98. The model page is authoritative when prices change; polling is not generation time.

## Development and FAQ

python -m py_compile server.py checks syntax. Optional tests use a local mocked urlopen; no key or generation is required. The official MCP SDK is not bundled, and a real host session has not been run here. A local output path is required for downloads; base64 is a fallback for clients without filesystem access.

Can I pass a local image? This minimal server does not upload files; obtain a media URL through the documented upload flow first. Why no automatic polling? Host-side polling keeps the request ID resumable after an interrupted call. Does it expose video? Yes, only this model and three explicit operations; it is not a general gateway.

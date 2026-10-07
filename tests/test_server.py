import json
import os
import tempfile
import unittest
from pathlib import Path
from urllib.request import Request

from seedance_client import SeedanceClient, VideoAPIError


class FakeResponse:
    def __init__(self, payload=b"{}"):
        self.payload = payload

    def read(self, amount=-1):
        return self.payload if amount == -1 else self.payload[:amount]

    def close(self):
        pass


class Recorder:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, request, timeout):
        self.requests.append((request, timeout))
        return FakeResponse(self.responses.pop(0))


class RequestRules(unittest.TestCase):
    def client(self, response=b'{"request_id":"job_1"}'):
        recorder = Recorder([response])
        return SeedanceClient("test-key", base_url="https://api.test/v1", opener=recorder), recorder

    def test_each_supported_mode_builds_canonical_body(self):
        client, _ = self.client()
        text = client.build_request(
            prompt="a fox", mode="text", duration=5, resolution="720p",
            aspect_ratio="16:9", generate_audio=True, start_image=None,
            end_image=None, reference_images=[], reference_videos=[],
            reference_audios=[], edit_video=None,
        )
        self.assertEqual(text["model"], "seedance-2.5")
        self.assertEqual(text["aspect_ratio"], "16:9")
        frame = client.build_request(
            prompt="a fox", mode="first_last_frames", duration=6, resolution="1080p",
            aspect_ratio="16:9", generate_audio=False, start_image="https://x.test/a.png",
            end_image="https://x.test/b.png", reference_images=[], reference_videos=[],
            reference_audios=[], edit_video=None,
        )
        self.assertEqual(frame["aspect_ratio"], "adaptive")
        self.assertEqual(frame["end_image"], {"url": "https://x.test/b.png"})
        refs = client.build_request(
            prompt="match the beat", mode="multimodal_reference", duration=5,
            resolution="720p", aspect_ratio="1:1", generate_audio=True,
            start_image=None, end_image=None, reference_images=["https://x.test/a.png"],
            reference_videos=[], reference_audios=["https://x.test/a.wav"], edit_video=None,
        )
        self.assertEqual(refs["reference_images"][0]["url"], "https://x.test/a.png")
        edit = client.build_request(
            prompt="remove the logo", mode="video_edit", duration=5, resolution="720p",
            aspect_ratio="16:9", generate_audio=True, start_image=None, end_image=None,
            reference_images=[], reference_videos=[], reference_audios=[],
            edit_video="https://x.test/source.mp4",
        )
        self.assertNotIn("duration", edit)
        self.assertEqual(edit["omni_reference_task_type"], "edit")

    def test_rules_reject_wrong_mode_combinations_and_urls(self):
        client, _ = self.client()
        args = dict(
            prompt="x", duration=5, resolution="720p", aspect_ratio="16:9",
            generate_audio=True, start_image=None, end_image=None,
            reference_images=[], reference_videos=[], reference_audios=[], edit_video=None,
        )
        with self.assertRaises(ValueError):
            client.build_request(mode="text", **{**args, "reference_images": ["https://x.test/a"]})
        with self.assertRaises(ValueError):
            client.build_request(mode="start_image", **{**args, "start_image": "http://x.test/a"})
        with self.assertRaises(ValueError):
            client.build_request(mode="video_edit", **args)
        with self.assertRaises(ValueError):
            client.build_request(mode="text", **{**args, "duration": 31})

    def test_api_request_has_auth_and_descriptive_user_agent(self):
        client, recorder = self.client()
        result = client.submit({"model": "seedance-2.5", "prompt": "x"})
        self.assertEqual(result["request_id"], "job_1")
        request, _ = recorder.requests[0]
        self.assertEqual(request.get_header("Authorization"), "Bearer test-key")
        self.assertEqual(request.get_header("User-agent"), "seedance-2-5-video-mcp/1.0")
        self.assertEqual(json.loads(request.data)["model"], "seedance-2.5")


class FilesAndUploads(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        os.environ["VIDEO_MCP_MEDIA_ROOT"] = self.temp.name

    def tearDown(self):
        os.environ.pop("VIDEO_MCP_MEDIA_ROOT", None)

    def test_download_publishes_only_after_done_and_never_overwrites(self):
        recorder = Recorder([b'{"status":"done"}', b"mp4-bytes", b'{"status":"done"}'])
        client = SeedanceClient("test-key", base_url="https://api.test/v1", opener=recorder)
        output = client.download("job_1", "renders/movie.mp4")
        self.assertEqual(Path(output["path"]).read_bytes(), b"mp4-bytes")
        with self.assertRaises(FileExistsError):
            client.download("job_1", "renders/movie.mp4")

    def test_upload_ticket_key_is_not_sent_to_storage(self):
        source = Path(self.temp.name) / "clip.mp4"
        source.write_bytes(b"video")
        recorder = Recorder([
            b'{"upload_url":"https://storage.test/put","media_url":"https://storage.test/media"}',
            b"",
        ])
        client = SeedanceClient("test-key", base_url="https://api.test/v1", opener=recorder)
        result = client.upload(str(source))
        self.assertEqual(result["media_url"], "https://storage.test/media")
        ticket_request, put_request = [entry[0] for entry in recorder.requests]
        self.assertEqual(ticket_request.get_header("Authorization"), "Bearer test-key")
        self.assertIsNone(put_request.get_header("Authorization"))
        self.assertEqual(put_request.get_header("User-agent"), "seedance-2-5-video-mcp/1.0")


if __name__ == "__main__":
    unittest.main()

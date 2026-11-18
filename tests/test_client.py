import json
import os
import unittest
from urllib.parse import parse_qs, urlsplit

import pipefetch
from pipefetch import (
    AuthenticationError,
    InsufficientCreditsError,
    InvalidRequestError,
    NotFoundError,
    Pipefetch,
    PipefetchError,
    RateLimitError,
)


class FakeTransport:
    """Answers from a queue and records what it was asked. The last answer repeats."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []

    def __call__(self, url, headers, timeout):
        self.calls.append((url, headers, timeout))
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(answer, Exception):
            raise answer
        status, body = answer
        return status, body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")


def ok(data, credits=None):
    return 200, {"data": data, "credits": credits or {"used": 1, "remaining": 99}}


def error(status, code, message="nope"):
    return status, {"error": {"code": code, "message": message}}


def client(transport, **options):
    return Pipefetch("pf_test", transport=transport, retry_delay=0.001, **options)


class ClientTest(unittest.TestCase):
    def test_a_request_sends_the_key_in_the_header_and_returns_the_data(self):
        fake = FakeTransport(ok({"videoId": "jNQXAC9IVRw", "text": "All right"}))
        pf = client(fake)
        transcript = pf.transcript("https://youtu.be/jNQXAC9IVRw", lang="en", format="srt", segments=False)
        self.assertEqual(transcript, {"videoId": "jNQXAC9IVRw", "text": "All right"})
        self.assertEqual(pf.credits, {"used": 1, "remaining": 99})
        url, headers, timeout = fake.calls[0]
        parts = urlsplit(url)
        self.assertEqual(parts.scheme + "://" + parts.netloc + parts.path, "https://pipefetch.com/v1/youtube/transcript")
        self.assertEqual(
            parse_qs(parts.query),
            {"video": ["https://youtu.be/jNQXAC9IVRw"], "lang": ["en"], "format": ["srt"], "segments": ["false"]},
        )
        self.assertEqual(headers["x-api-key"], "pf_test")
        self.assertEqual(headers["user-agent"], "pipefetch-python/" + pipefetch.__version__)
        self.assertNotIn("pf_test", url, "the key never goes into the URL")
        self.assertEqual(timeout, 90.0)

    def test_every_method_calls_its_endpoint_with_its_parameters(self):
        fake = FakeTransport(ok({}))
        pf = client(fake)
        pf.video("jNQXAC9IVRw")
        pf.channel("@mkbhd")
        pf.channel_videos("@mkbhd", limit=5)
        pf.channel_shorts("@MrBeast")
        pf.search("web scraping", sort="newest", uploaded="week", limit=40)
        pf.comments("jNQXAC9IVRw", limit=100, sort="newest")
        pf.website_contacts("apify.com", pages=3)
        pf.website_brand("https://stripe.com")
        pf.instagram_profile("@nasa", posts=False)
        pf.account()
        asked = [url.replace("https://pipefetch.com", "") for url, _, _ in fake.calls]
        self.assertEqual(
            asked,
            [
                "/v1/youtube/video?video=jNQXAC9IVRw",
                "/v1/youtube/channel?channel=%40mkbhd",
                "/v1/youtube/channel/videos?channel=%40mkbhd&limit=5",
                "/v1/youtube/channel/shorts?channel=%40MrBeast",
                "/v1/youtube/search?q=web+scraping&limit=40&sort=newest&uploaded=week",
                "/v1/youtube/comments?video=jNQXAC9IVRw&limit=100&sort=newest",
                "/v1/web/contacts?url=apify.com&pages=3",
                "/v1/web/brand?url=https%3A%2F%2Fstripe.com",
                "/v1/instagram/profile?username=%40nasa&posts=false",
                "/v1/account",
            ],
        )

    def test_each_kind_of_error_answer_becomes_its_own_error_class(self):
        cases = [
            (error(400, "invalid_request"), InvalidRequestError),
            (error(401, "unauthorized"), AuthenticationError),
            (error(402, "insufficient_credits"), InsufficientCreditsError),
            (error(404, "no_transcript", "This video has no captions. Nothing was charged."), NotFoundError),
            (error(429, "not_found_limit"), RateLimitError),
        ]
        for answer, error_class in cases:
            fake = FakeTransport(answer)
            with self.assertRaises(error_class) as raised:
                client(fake).transcript("jNQXAC9IVRw")
            self.assertIsInstance(raised.exception, PipefetchError)
            self.assertEqual((raised.exception.status, raised.exception.code), (answer[0], answer[1]["error"]["code"]))
            self.assertEqual(str(raised.exception), answer[1]["error"]["message"])
            self.assertEqual(len(fake.calls), 1, "%d must not be retried" % answer[0])

    def test_trouble_on_the_way_is_retried_then_succeeds(self):
        fake = FakeTransport(error(503, "busy"), OSError("connection reset"), error(429, "rate_limited"), ok({"id": "UC1"}))
        self.assertEqual(client(fake, retries=3).channel("@mkbhd"), {"id": "UC1"})
        self.assertEqual(len(fake.calls), 4)

    def test_when_the_retries_run_out_the_last_error_is_raised(self):
        busy = FakeTransport(error(502, "upstream_error", "YouTube did not answer."))
        with self.assertRaises(PipefetchError) as raised:
            client(busy).video("jNQXAC9IVRw")
        self.assertEqual((raised.exception.status, raised.exception.code), (502, "upstream_error"))
        self.assertEqual(len(busy.calls), 3, "one try and two retries by default")

        offline = FakeTransport(TimeoutError("timed out"))
        with self.assertRaises(PipefetchError) as raised:
            client(offline, retries=0).video("jNQXAC9IVRw")
        self.assertIsNone(raised.exception.status)
        self.assertIsInstance(raised.exception.__cause__, TimeoutError)
        self.assertEqual(len(offline.calls), 1)

    def test_an_answer_that_is_not_json_is_an_error_not_a_crash(self):
        fake = FakeTransport((500, b"<html>oops</html>"))
        with self.assertRaises(PipefetchError) as raised:
            client(fake, retries=0).video("jNQXAC9IVRw")
        self.assertEqual((raised.exception.status, raised.exception.code), (500, None))

    def test_the_key_comes_from_the_argument_or_the_environment_and_is_required(self):
        before = os.environ.pop("PIPEFETCH_API_KEY", None)
        try:
            with self.assertRaises(PipefetchError):
                Pipefetch()
            os.environ["PIPEFETCH_API_KEY"] = "pf_env"
            fake = FakeTransport(ok({}))
            Pipefetch(transport=fake).account()
            self.assertEqual(fake.calls[0][1]["x-api-key"], "pf_env")
        finally:
            os.environ.pop("PIPEFETCH_API_KEY", None)
            if before is not None:
                os.environ["PIPEFETCH_API_KEY"] = before

    def test_a_custom_base_url_is_used_without_its_trailing_slash(self):
        fake = FakeTransport(ok({}))
        client(fake, base_url="http://localhost:8787/").account()
        self.assertEqual(fake.calls[0][0], "http://localhost:8787/v1/account")


if __name__ == "__main__":
    unittest.main()

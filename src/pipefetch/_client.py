"""The Pipefetch client. Standard library only: no dependencies to install or to conflict with."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Dict, Optional, Tuple

__version__ = "0.3.0"

DEFAULT_BASE_URL = "https://pipefetch.com"
# Statuses that mean "try again": the request was not charged and may succeed on a retry.
_RETRYABLE_STATUS = frozenset({502, 503, 504})

# (url, headers, timeout in seconds) -> (HTTP status, body bytes). Raises OSError when the API cannot be reached.
Transport = Callable[[str, Dict[str, str], float], Tuple[int, bytes]]


class PipefetchError(Exception):
    """Any error answer from the API, or a failure to reach it. Nothing is charged for an error.

    ``status`` is the HTTP status (``None`` when the API was not reached) and ``code`` is the API's
    error code, such as ``"no_transcript"`` or ``"insufficient_credits"``.
    """

    def __init__(self, message: str, status: Optional[int] = None, code: Optional[str] = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code


class InvalidRequestError(PipefetchError):
    """400: a parameter is missing, unknown or not allowed."""


class AuthenticationError(PipefetchError):
    """401: the API key is missing or not valid."""


class InsufficientCreditsError(PipefetchError):
    """402: the account has fewer credits than the request costs."""


class NotFoundError(PipefetchError):
    """404: YouTube has nothing to return for this request (no such video, no captions, no results). Not charged."""


class RateLimitError(PipefetchError):
    """429: too many requests in a minute, or too many requests today that found nothing."""


_ERROR_CLASSES = {
    400: InvalidRequestError,
    401: AuthenticationError,
    402: InsufficientCreditsError,
    404: NotFoundError,
    429: RateLimitError,
}


def _urllib_transport(url: str, headers: Dict[str, str], timeout: float) -> Tuple[int, bytes]:
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        # An error status is still an answer from the API: its body says what went wrong.
        return error.code, error.read()


class Pipefetch:
    """YouTube transcripts, videos, channels, search and comments as JSON.

    >>> pf = Pipefetch("pf_...")                      # or set PIPEFETCH_API_KEY
    >>> pf.transcript("jNQXAC9IVRw")["text"]          # doctest: +SKIP

    Each method is one request and returns the ``data`` of the answer as a ``dict``. Videos can be
    given as an ID or any YouTube URL; channels as a handle (``@mkbhd``), a channel ID or a URL.
    After a request that returned data, ``credits`` holds ``{"used": ..., "remaining": ...}``.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 90.0,
        retries: int = 2,
        retry_delay: float = 1.0,
        transport: Optional[Transport] = None,
    ) -> None:
        self._api_key = api_key or os.environ.get("PIPEFETCH_API_KEY")
        if not self._api_key:
            raise PipefetchError(
                "Missing API key. Pass it to Pipefetch() or set PIPEFETCH_API_KEY. "
                "Create one at https://pipefetch.com/dashboard"
            )
        self._base_url = base_url.rstrip("/")
        # Every answer is fetched live from YouTube and usually takes 2 to 7 seconds; 90 leaves room for a slow one.
        self._timeout = timeout
        self._retries = retries
        self._retry_delay = retry_delay
        self._transport = transport or _urllib_transport
        self.credits: Optional[Dict[str, int]] = None

    def transcript(
        self,
        video: str,
        *,
        lang: Optional[str] = None,
        format: Optional[str] = None,
        segments: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """The transcript of a video. ``format`` is "text", "timestamped", "srt" or "vtt". 1 credit."""
        return self._get("/v1/youtube/transcript", video=video, lang=lang, format=format, segments=segments)

    def video(self, video: str) -> Dict[str, Any]:
        """Exact views, likes and comment count, description, tags, chapters and channel of one video. 1 credit."""
        return self._get("/v1/youtube/video", video=video)

    def channel(self, channel: str) -> Dict[str, Any]:
        """Subscribers, video count, description, keywords and avatar of a channel. 1 credit."""
        return self._get("/v1/youtube/channel", channel=channel)

    def channel_videos(self, channel: str, *, limit: Optional[int] = None) -> Dict[str, Any]:
        """The latest uploads of a channel, newest first (up to 30), with the channel itself. 1 credit."""
        return self._get("/v1/youtube/channel/videos", channel=channel, limit=limit)

    def channel_shorts(self, channel: str, *, limit: Optional[int] = None) -> Dict[str, Any]:
        """The latest Shorts of a channel, newest first (up to 40). 1 credit."""
        return self._get("/v1/youtube/channel/shorts", channel=channel, limit=limit)

    def search(
        self,
        query: str,
        *,
        limit: Optional[int] = None,
        type: Optional[str] = None,
        sort: Optional[str] = None,
        uploaded: Optional[str] = None,
        country: Optional[str] = None,
        lang: Optional[str] = None,
    ) -> Dict[str, Any]:
        """YouTube search results for a query (up to 40), with sorting and filters. 1 credit."""
        return self._get(
            "/v1/youtube/search", q=query, limit=limit, type=type, sort=sort, uploaded=uploaded, country=country, lang=lang
        )

    def comments(self, video: str, *, limit: Optional[int] = None, sort: Optional[str] = None) -> Dict[str, Any]:
        """Top or newest comments of a video (up to 100). 1 credit per started 20 comments."""
        return self._get("/v1/youtube/comments", video=video, limit=limit, sort=sort)

    def website_contacts(self, url: str, *, pages: Optional[int] = None) -> Dict[str, Any]:
        """The emails, phone numbers and social profiles a website publishes, with its contact page and address. 1 credit."""
        return self._get("/v1/web/contacts", url=url, pages=pages)

    def website_brand(self, url: str) -> Dict[str, Any]:
        """A company's logo, icon, brand colors, fonts, description and social profiles, read from its website. 1 credit."""
        return self._get("/v1/web/brand", url=url)

    def instagram_profile(self, username: str, *, posts: Optional[bool] = None) -> Dict[str, Any]:
        """A public Instagram account: exact counts, bio, links, engagement and its latest posts and Reels. 2 credits."""
        return self._get("/v1/instagram/profile", username=username, posts=posts)

    def account(self) -> Dict[str, Any]:
        """The account behind the key: its email and credit balance. Free."""
        return self._get("/v1/account")

    def _get(self, path: str, **params: Any) -> Dict[str, Any]:
        query = {
            name: ("true" if value is True else "false" if value is False else str(value))
            for name, value in params.items()
            if value is not None
        }
        url = self._base_url + path + ("?" + urllib.parse.urlencode(query) if query else "")
        headers = {
            "x-api-key": self._api_key,
            "accept": "application/json",
            "user-agent": "pipefetch-python/" + __version__,
        }
        last_error: PipefetchError = PipefetchError("The request was not sent.")
        for attempt in range(self._retries + 1):
            if attempt > 0:
                time.sleep(self._retry_delay * 2 ** (attempt - 1))
            try:
                status, raw = self._transport(url, headers, self._timeout)
            except OSError as error:  # URLError, timeouts and connection failures are all OSError
                last_error = PipefetchError("Could not reach the Pipefetch API: %s" % error)
                last_error.__cause__ = error
                continue
            try:
                body = json.loads(raw.decode("utf-8")) if raw else None
            except ValueError:
                body = None
            if 200 <= status < 300 and isinstance(body, dict) and "data" in body:
                if isinstance(body.get("credits"), dict):
                    self.credits = body["credits"]
                return body["data"]
            detail = body.get("error") if isinstance(body, dict) and isinstance(body.get("error"), dict) else {}
            code = detail.get("code")
            message = detail.get("message") or "The API answered %d." % status
            last_error = _ERROR_CLASSES.get(status, PipefetchError)(message, status=status, code=code)
            # Worth another try: trouble on the way to YouTube, or a short burst over the per-minute limit.
            if not (status in _RETRYABLE_STATUS or (status == 429 and code == "rate_limited")):
                break
        raise last_error

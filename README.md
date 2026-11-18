# pipefetch

YouTube transcripts, video details, channels, search and comments as JSON, from Python, and what a
company's website publishes (its contact details and its brand), plus public Instagram profiles. This
is the client for the [Pipefetch API](https://pipefetch.com).

- No dependencies: it uses only the standard library. Python 3.9 or newer.
- Runs the same on your laptop and on a server, with no proxies to manage.
- You only pay for requests that return data. A video without captions or an empty search costs nothing.

```bash
pip install pipefetch
```

## Quick start

Create an API key at [pipefetch.com/dashboard](https://pipefetch.com/dashboard). A new account has
100 free credits and needs no card.

```python
import os
from pipefetch import Pipefetch

pf = Pipefetch(os.environ["PIPEFETCH_API_KEY"])

transcript = pf.transcript("https://www.youtube.com/watch?v=jNQXAC9IVRw")
print(transcript["title"])
print(transcript["text"])
```

`Pipefetch()` without an argument reads the key from the `PIPEFETCH_API_KEY` environment variable.

## Methods

Each method is one request and returns the `data` of the answer as a `dict`. Videos can be given as
an ID or any YouTube URL; channels as a handle (`@mkbhd`), a channel ID or a channel URL; websites as
a domain (`stripe.com`) or any address on the site; Instagram accounts as a username, a handle or a
profile URL.

| Method | Returns | Credits |
|---|---|---|
| `transcript(video, lang=, format=, segments=)` | Transcript as text, timed segments, SRT or WebVTT | 1 |
| `video(video)` | Exact views, likes, comment count, description, tags, chapters, channel | 1 |
| `channel(channel)` | Subscribers, video count, description, keywords, avatar | 1 |
| `channel_videos(channel, limit=)` | The latest uploads, up to 30, with views and duration | 1 |
| `channel_shorts(channel, limit=)` | The latest Shorts, up to 40 | 1 |
| `search(query, limit=, type=, sort=, uploaded=, country=, lang=)` | Search results, up to 40 | 1 |
| `comments(video, limit=, sort=)` | Top or newest comments, up to 100 | 1 per started 20 |
| `website_contacts(url, pages=)` | The emails, phone numbers and social profiles a website publishes, its contact page and address | 1 |
| `website_brand(url)` | A company's name, logo, icon, brand colors, fonts and social profiles | 1 |
| `instagram_profile(username, posts=)` | A public Instagram account: exact followers, bio, links, engagement, latest posts and Reels | 2 |
| `account()` | The account's email and credit balance | free |

Every parameter and every field of the answers is in the [reference](https://pipefetch.com/docs).

```python
# A subtitle file
srt = pf.transcript("jNQXAC9IVRw", format="srt", lang="en")
with open("subtitles.srt", "w", encoding="utf-8") as f:
    f.write(srt["text"])

# The latest uploads of a channel
latest = pf.channel_videos("@mkbhd", limit=10)
for video in latest["videos"]:
    print(video["publishedAt"], video["viewCount"], video["title"])

# Search, newest first, uploaded this week
results = pf.search("web scraping tutorial", sort="newest", uploaded="week")["results"]

# The top 40 comments (2 credits)
comments = pf.comments("jNQXAC9IVRw", limit=40)["comments"]

# The contact details a company's website publishes
contacts = pf.website_contacts("apify.com")
print(contacts["primaryEmail"], contacts["socials"]["linkedin"])

# A company's logo and colors
brand = pf.website_brand("stripe.com")
print(brand["name"], brand["logo"], brand["colors"]["primary"])

# A public Instagram account (2 credits)
profile = pf.instagram_profile("nasa")
print(profile["followerCount"], profile["engagementRate"], len(profile["latestPosts"]))
```

## Credits

After a request that returned data, `pf.credits` holds what it cost and what is left:

```python
pf.video("jNQXAC9IVRw")
print(pf.credits)  # {'used': 1, 'remaining': 98}
```

## Errors

Every error is a `PipefetchError` with the HTTP `status` and the API's `code`. No error is ever
charged. The common ones have their own classes:

| Class | Status | When |
|---|---|---|
| `NotFoundError` | 404 | There is nothing to return: no such video, no captions, no results, comments turned off, a website that is unreachable or shows no contacts, no such Instagram account |
| `InvalidRequestError` | 400 | A parameter is missing, unknown or not allowed |
| `AuthenticationError` | 401 | The API key is missing or not valid |
| `InsufficientCreditsError` | 402 | The account has fewer credits than the request costs |
| `RateLimitError` | 429 | More than 120 requests in a minute, or too many requests today that found nothing |

```python
from pipefetch import NotFoundError, Pipefetch

pf = Pipefetch()
for video_id in video_ids:
    try:
        text = pf.transcript(video_id)["text"]
    except NotFoundError:
        continue  # no captions for this one; not charged
    ...
```

Network failures, statuses 502, 503 and 504, and the per-minute rate limit are retried twice by
default, with a growing pause. Change that with `retries=` and `retry_delay=`.

## Options

```python
pf = Pipefetch(
    "pf_...",          # default: the PIPEFETCH_API_KEY environment variable
    timeout=90.0,      # seconds per request; answers are fetched live and usually take 2 to 7
    retries=2,
    retry_delay=1.0,
)
```

## Good to know

- Every answer is fetched live from YouTube, Instagram or the website you name, so it is current and
  a request takes a few seconds.
- Each request returns one page: the latest 30 uploads, up to 40 search results, up to 100 comments.
- Keep the key on your server. Anyone who has it can spend its credits.
- Pipefetch is an independent service. It is not affiliated with, endorsed by or sponsored by
  YouTube or Google.

## Links

- [Documentation](https://pipefetch.com/docs)
- [Guides](https://pipefetch.com/guides), including [why youtube-transcript-api gets blocked on servers](https://pipefetch.com/guides/youtube-transcript-api-request-blocked)
- [Pricing](https://pipefetch.com/pricing)
- Questions: support@pipefetch.com

MIT licensed.

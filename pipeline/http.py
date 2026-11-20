"""A small HTTP helper with retries. Standard library only, so the daily run has nothing to install."""
import time
import urllib.error
import urllib.request

USER_AGENT = "eu-market-entry-check/1.0 (+https://github.com/Unmesh30/eu-market-entry-check)"


def fetch(url, data=None, headers=None, timeout=90, tries=4, pause=5.0):
    """Return the response body as bytes. POSTs when `data` is given.

    Retries network errors, rate limits (429) and server errors (5xx);
    other HTTP errors fail at once because retrying would not help.
    """
    last_error = None
    for attempt in range(tries):
        request = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT, **(headers or {})})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            last_error = error
            if error.code < 500 and error.code != 429:
                break
        except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
            last_error = error
        if attempt < tries - 1:
            time.sleep(pause * (attempt + 1))
    raise RuntimeError(f"could not reach {url.split('?')[0]} ({last_error})")

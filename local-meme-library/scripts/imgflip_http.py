"""Low-frequency, cached, same-origin public Imgflip HTTP reads."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time
import urllib.parse
import urllib.request
import urllib.robotparser

BASE = 'https://imgflip.com'
USER_AGENT = 'local-meme-library/0.2 (+https://github.com/songshikang0111/meme-generator)'
LISTINGS = {'image': '/memetemplates', 'gif': '/gif-templates'}


def now():
    return datetime.now(timezone.utc).isoformat()


def write_cache(path, value):
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.cache-')
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('Unexpected redirect; stopped without following: ' + newurl)


class GentleClient:
    def __init__(self, cache_dir, delay=3.0, detail_template_id=None):
        if delay < 2:
            raise ValueError('Request delay must be at least two seconds')
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.delay = delay
        self.detail_template_id = detail_template_id
        self.last = None
        self.network_requests = 0
        self.cache_hits = 0
        self.robots = None
        self.opener = urllib.request.build_opener(NoRedirect())

    def fetch(self, url):
        parts = urllib.parse.urlsplit(url)
        if parts.scheme != 'https' or parts.netloc != 'imgflip.com' or parts.fragment:
            raise ValueError('Only same-origin HTTPS listing requests are supported')
        if parts.path != '/robots.txt':
            detail_path = '/memetemplate/' + self.detail_template_id if self.detail_template_id else None
            if parts.path not in LISTINGS.values() and parts.path != detail_path:
                raise ValueError('Only public listings or the explicitly requested detail page are allowed')
            query = urllib.parse.parse_qs(parts.query)
            if set(query) - {'page'} or any(not re.fullmatch(r'[1-9][0-9]*', v) for v in query.get('page', [])):
                raise ValueError('Only ordinary page pagination is allowed')
            if self.robots is None or not self.robots.can_fetch(USER_AGENT, url):
                raise ValueError('robots.txt does not allow this request: ' + url)
        path = self.cache_dir / (hashlib.sha256(url.encode()).hexdigest() + '.json')
        if path.exists():
            cached = json.loads(path.read_text())
            age = datetime.now(timezone.utc).timestamp() - datetime.fromisoformat(cached['retrieved_at']).timestamp()
            if cached.get('url') == url and 0 <= age < 24 * 3600:
                self.cache_hits += 1
                return {**cached, 'from_cache': True}
        if self.last is not None:
            time.sleep(max(0, self.delay - (time.monotonic() - self.last)))
        request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT, 'Accept': 'text/html,text/plain;q=0.9'})
        self.last = time.monotonic()
        self.network_requests += 1
        # No retry, parallel requests, cookies, proxy rotation, or access-control workarounds.
        with self.opener.open(request, timeout=40) as response:
            body = response.read(2_000_001)
            if len(body) > 2_000_000:
                raise ValueError('Listing exceeds 2 MB response limit')
            if response.headers.get_content_type() not in ('text/html', 'text/plain'):
                raise ValueError('Unexpected response content type')
        result = {'url': url, 'retrieved_at': now(), 'sha256': hashlib.sha256(body).hexdigest(),
                  'bytes': len(body), 'text': body.decode('utf-8'), 'from_cache': False}
        write_cache(path, result)
        return result

    def load_robots(self):
        response = self.fetch(BASE + '/robots.txt')
        parser = urllib.robotparser.RobotFileParser()
        parser.parse(response['text'].splitlines())
        self.robots = parser
        delay = parser.crawl_delay(USER_AGENT)
        if delay is not None:
            self.delay = max(self.delay, delay)
        return {k: v for k, v in response.items() if k != 'text'}

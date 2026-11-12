"""Public GitHub releases with a short cache and official-page quota fallback.

No credentials are read, stored or distributed. API cooldown is shared by the
release lookups in this portable copy and respected before another API request.
"""
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import threading
import time
import urllib.error
import urllib.parse
import uuid

LOCK = threading.RLock()
TTL = 300


def validate(data, repository):
    rows = data if isinstance(data, list) else [data]
    if len(rows) > 100:
        raise ValueError('GitHub release list too large')
    for row in rows:
        if not isinstance(row, dict) or not re.fullmatch(r'[A-Za-z0-9._-]{1,120}', row.get('tag_name', '')):
            raise ValueError('Invalid GitHub release tag')
        assets = row.get('assets', [])
        if not isinstance(assets, list) or len(assets) > 100:
            raise ValueError('Invalid GitHub asset list')
        for item in assets:
            name = item.get('name', '')
            if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,180}', name):
                raise ValueError('Invalid GitHub asset name')
            expected = f"https://github.com/{repository}/releases/download/{row['tag_name']}/{name}"
            if item.get('browser_download_url') != expected or type(item.get('size')) is not int or item['size'] <= 0:
                raise ValueError('Invalid GitHub asset source or size')
            if item.get('digest') and not re.fullmatch(r'sha256:[0-9a-f]{64}', item['digest']):
                raise ValueError('Invalid GitHub asset digest')
    return data


def save(path, data):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Do not follow a user-created junction/symlink for cache writes.
        for item in (path.parent, path):
            if item.exists() and (item.is_symlink() or getattr(item.lstat(), 'st_file_attributes', 0) & 1024):
                return
        temp = path.with_name('.' + uuid.uuid4().hex + '.tmp')
        temp.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        temp.replace(path)
    except OSError:
        pass  # A failed cache write must not turn a verified online lookup into failure.


def read(path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def quota_error(error):
    return (isinstance(error, urllib.error.HTTPError) and error.code in (403, 429)
            and (error.headers.get('X-RateLimit-Remaining') == '0'
                 or error.headers.get('Retry-After') is not None or error.code == 429))


class Fragments(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'include-fragment' and '/releases/expanded_assets/' in attrs.get('src', ''):
            self.urls.append(attrs['src'])


class Assets(HTMLParser):
    def __init__(self, repository, tag):
        super().__init__()
        self.prefix = f'/{repository}/releases/download/{tag}/'
        self.depth = 0
        self.current = None
        self.items = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'li':
            if not self.depth:
                self.current = {}
            self.depth += 1
        if not self.depth:
            return
        if tag == 'a':
            href = attrs.get('href', '')
            if href.startswith(self.prefix):
                name = href[len(self.prefix):]
                if re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,180}', name):
                    self.current.update(name=name, browser_download_url='https://github.com'+href, state='uploaded')
        if tag == 'clipboard-copy' and re.fullmatch(r'sha256:[0-9a-f]{64}', attrs.get('value', '')):
            self.current['digest'] = attrs['value']

    def handle_endtag(self, tag):
        if tag == 'li' and self.depth:
            self.depth -= 1
            if not self.depth and self.current.get('name'):
                self.items.append(self.current)


def web_release(repository, tag, fetch, head):
    page_url = f'https://github.com/{repository}/releases/' + ('latest' if tag is None else 'tag/'+tag)
    page = fetch(page_url, 5 * 1024**2).decode('utf-8')
    if re.search(r'class="[^"\n]*\bLabel\b[^"\n]*"[^>]*>\s*Pre-release\s*<', page, re.I):
        raise ValueError('Pre-release is not a stable update')
    fragments = Fragments()
    fragments.feed(page)
    prefix = f'https://github.com/{repository}/releases/expanded_assets/'
    urls = {urllib.parse.urljoin('https://github.com', url) for url in fragments.urls}
    urls = {url for url in urls if url.startswith(prefix)
            and re.fullmatch(r'[A-Za-z0-9._-]{1,120}', url[len(prefix):])}
    if len(urls) != 1:
        raise ValueError('Official GitHub release asset list is ambiguous or unavailable')
    url = urls.pop()
    actual_tag = url[len(prefix):]
    if tag is not None and tag != actual_tag:
        raise ValueError('Official GitHub release tag mismatch')
    parser = Assets(repository, actual_tag)
    parser.feed(fetch(url, 2 * 1024**2).decode('utf-8'))
    if not parser.items or len(parser.items) > 100:
        raise ValueError('Official GitHub release has no valid assets')
    for item in parser.items:
        item['size'] = head(item['browser_download_url'])
    return validate({'tag_name':actual_tag, 'draft':False, 'prerelease':False,
                     'assets':parser.items, '_retrieved_via':'official release page'}, repository)


def release_data(repository, selector, fetch, head, cache_root: Path, version_hint=None):
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
        raise ValueError('Invalid GitHub repository')
    if not (selector == 'latest' or re.fullmatch(r'tags/[A-Za-z0-9._-]{1,120}', selector)
            or re.fullmatch(r'\?per_page=100&page=[1-5]', selector)):
        raise ValueError('Invalid GitHub release selector')
    key = hashlib.sha256((repository+'|'+selector+'|'+str(version_hint)).encode()).hexdigest()
    path = cache_root/(key+'.json')
    with LOCK:
        now = time.time()
        cached = read(path)
        saved = cached.get('saved', 0) if isinstance(cached, dict) else 0
        if isinstance(saved, (int, float)) and isinstance(cached, dict) and 0 <= now-saved < TTL:
            try:
                return validate(cached['data'], repository)
            except (KeyError, ValueError, TypeError):
                pass
        rate_path = cache_root/'api-cooldown.json'
        cooldown = read(rate_path)
        until = cooldown.get('until', 0) if isinstance(cooldown, dict) else 0
        limited = isinstance(until, (int, float)) and now < until < now+86400
        if not limited:
            suffix = selector if selector.startswith('?') else '/'+selector
            try:
                data = validate(json.loads(fetch(f'https://api.github.com/repos/{repository}/releases{suffix}',
                                                6 * 1024**2)), repository)
                save(path, {'saved':now, 'data':data})
                return data
            except urllib.error.HTTPError as error:
                if not quota_error(error):
                    raise
                try:
                    until = max(now+60, float(error.headers.get('X-RateLimit-Reset', 0)),
                                now+float(error.headers.get('Retry-After', 0)))
                except ValueError:
                    until = now+60
                save(rate_path, {'until':min(until, now+86400-1)})
        # This uses the author's ordinary public release page, never a proxy,
        # credentials, altered IP, or repeated requests to an exhausted API.
        if selector.startswith('?'):
            if not version_hint or not re.fullmatch(r'[A-Za-z0-9._-]{1,119}', version_hint):
                raise ValueError('Historical release requires an exact version')
            for tag in (version_hint, 'v'+version_hint):
                try:
                    data = [web_release(repository, tag, fetch, head)]
                    break
                except urllib.error.HTTPError as error:
                    if error.code != 404:
                        raise
            else:
                raise ValueError('Author no longer provides this historical release')
        else:
            data = web_release(repository, None if selector == 'latest' else selector[5:], fetch, head)
        save(path, {'saved':now, 'data':data})
        return data

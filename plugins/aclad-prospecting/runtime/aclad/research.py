"""Private, resumable public website evidence. Collected text is inert data.

The collector never activates portfolio/rules, invokes a provider or sends data.
It keeps snapshots in the existing transactional analysis records; no corpus is
written to the plugin tree or loaded wholesale into instruction context.
"""
from __future__ import annotations

import base64
import binascii
from datetime import timedelta
from hashlib import sha256
from html.parser import HTMLParser
import re
import time
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser
from uuid import uuid4
import xml.etree.ElementTree as ET

from .models import GateError, Payload, Record, now_utc, utc
from .store import Store
from .web_fetch import MAX_BODY, MAX_FETCH_SECONDS, MAX_REDIRECTS, TIMEOUT, USER_AGENT, _url, fetch_public, public_url

MAX_URLS = 500
MAX_COVERAGE_BUDGET = 100_000
MAX_ROBOTS_DELAY = 86_400
MAX_ROBOTS_RATE_COMPONENT = 1_000_000_000
MAX_TEXT = 50_000
CACHE_HOURS = 24
MAX_ATTEMPTS = 3
RETRY_SECONDS = 30
CATEGORIES = ('institutional', 'solutions', 'sectors', 'differentiators', 'cases', 'business_contacts', 'news')


def _subject(store: Store, subject_id: str, purpose: str) -> Record | None:
    if purpose == 'partner':
        if subject_id != store.scope.partner_id:
            raise GateError('partner_identity_mismatch')
        return store.get('profile', 'current')
    if purpose != 'prospect':
        raise GateError('invalid_research_purpose')
    account = store.get('account', subject_id)
    if not account or account.data.get('selected') is not True:
        raise GateError('selected_account_required')
    return account


def _identity_domain(record: Record | None, purpose: str) -> str | None:
    if not record:
        return None
    data = record.data.get('partner', {}) if purpose == 'partner' else record.data
    if not isinstance(data, dict):
        return None
    values = [data[key] for key in ('website', 'domain') if isinstance(data.get(key), str) and data[key].strip()]
    try:
        domains = {urlsplit(_url(value if '://' in value else 'https://' + value)).hostname for value in values}
        if len(domains) > 1:
            raise GateError('website_identity_mismatch')
        return next(iter(domains), None)
    except GateError:
        raise GateError('website_identity_mismatch') from None


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return parts.scheme + '://' + parts.netloc


def _validate_research_subject(store: Store, data: Payload) -> None:
    """A saved run cannot survive a correction to its subject's identity."""
    subject = _subject(store, data['subject_id'], data['purpose'])
    try:
        current = _identity_domain(subject, data['purpose'])
    except GateError:
        raise GateError('research_identity_review_required') from None
    if ((current and current != urlsplit(data['website']).hostname) or
            ('subject_domain' in data and data['subject_domain'] != current)):
        raise GateError('research_identity_review_required')


def _robots_delay(robots: RobotFileParser) -> float:
    delay = robots.crawl_delay(USER_AGENT) or 0
    if type(delay) is not int or not 0 <= delay <= MAX_ROBOTS_DELAY:
        raise GateError('invalid_robots_crawl_delay')
    rate = robots.request_rate(USER_AGENT)
    if rate:
        if (not 1 <= rate.requests <= MAX_ROBOTS_RATE_COMPONENT
                or not 1 <= rate.seconds <= MAX_ROBOTS_RATE_COMPONENT
                or rate.seconds > MAX_ROBOTS_DELAY * rate.requests):
            raise GateError('invalid_robots_request_rate')
        delay = max(delay, rate.seconds / rate.requests)
    return delay


def start_research(store: Store, subject_id: str, website: str, purpose: str, identity_confirmed: bool) -> Record:
    """Confirm identity before collection; resume a snapshot cached for 24 hours.

    purpose is partner or prospect; prospects must remain explicitly selected.
    An older snapshot is retained when a fresh run starts, preserving provenance.
    """
    if identity_confirmed is not True:
        raise GateError('website_identity_confirmation_required')
    subject = _subject(store, subject_id, purpose)
    website = _url(website)
    known = _identity_domain(subject, purpose)
    if known and known != urlsplit(website).hostname:
        raise GateError('website_identity_mismatch')
    now = now_utc()
    with store.transaction():
        for run in sorted(store.list('analysis'), key=lambda item: str(item.data.get('created_at', '')), reverse=True):
            data = run.data
            if data.get('type') == 'research_run' and data.get('subject_id') == subject_id and data.get('purpose') == purpose and data.get('website') == website:
                if utc(now) - utc(data['created_at']) < timedelta(hours=CACHE_HOURS):
                    return run
        origin = _origin(website)
        return store.put('analysis', 'research-' + uuid4().hex, {
            'type': 'research_run', 'subject_id': subject_id, 'purpose': purpose,
            'subject_domain': known,
            'website': website, 'identity_confirmed': True, 'origin': origin,
            'created_at': now, 'updated_at': now, 'status': 'pending',
            'queue': [{'url': origin + '/robots.txt', 'kind': 'robots', 'discovered_from': website},
                      {'url': website, 'kind': 'page', 'discovered_from': 'confirmed_website'},
                      {'url': origin + '/sitemap.xml', 'kind': 'sitemap', 'discovered_from': 'default_sitemap'}],
            'visited': [], 'page_ids': [], 'errors': [], 'exclusions': [], 'metadata_sources': [],
            'budget_deferred': [],
            'robots_text': None, 'limitations': ['external_news_not_searched'],
            'limits': {'max_urls': MAX_URLS, 'max_text_per_page': MAX_TEXT,
                       'max_response_bytes': MAX_BODY, 'cache_hours': CACHE_HOURS,
                       'allowed_origins': [origin], 'concurrency': 1,
                       'request_deadline_seconds': MAX_FETCH_SECONDS,
                       'socket_timeout_seconds': TIMEOUT, 'max_redirects': MAX_REDIRECTS,
                       'max_address_attempts': 2, 'max_url_attempts': MAX_ATTEMPTS,
                       'retry_delay_seconds': RETRY_SECONDS},
        }, None)


class _HTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.text = []
        self.links = []
        self.hidden = 0
        self.title = []
        self.in_title = False
        self.published_at = None

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag in {'script', 'style', 'noscript', 'template'}:
            self.hidden += 1
        if tag == 'title':
            self.in_title = True
        if tag == 'a' and values.get('href'):
            self.links.append(values['href'])
        date = None
        if tag == 'time':
            date = values.get('datetime')
        if tag == 'meta' and (values.get('property') or values.get('name') or '').lower() in {'article:published_time', 'datepublished', 'date'}:
            date = values.get('content')
        if isinstance(date, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}(?:T[^\s]{1,40})?', date):
            try:
                # Date-only source dates are valid; absent dates stay absent.
                from datetime import date as calendar_date
                calendar_date.fromisoformat(date[:10])
                self.published_at = date
            except ValueError:
                pass

    def handle_endtag(self, tag):
        if tag in {'script', 'style', 'noscript', 'template'}:
            self.hidden = max(0, self.hidden - 1)
        if tag == 'title':
            self.in_title = False

    def handle_data(self, data):
        if not self.hidden:
            if self.in_title:
                self.title.append(data)
            self.text.append(data)


def _categories(url: str, title: str, homepage: bool) -> list[str]:
    value = (urlsplit(url).path + ' ' + title).casefold()
    vocabulary = {
        'institutional': ('about', 'company', 'empresa', 'sobre', 'institucional'),
        'solutions': ('solution', 'solu', 'product', 'produto', 'service', 'servi'),
        'sectors': ('sector', 'setor', 'industry', 'industr', 'segment'),
        'differentiators': ('differen', 'diferenc', 'why-us', 'por-que'),
        'cases': ('case', 'customer', 'cliente', 'success'),
        'business_contacts': ('contact', 'contat', 'fale-conosco'),
        'news': ('news', 'noticia', 'notícia', 'press', 'imprensa'),
    }
    result = [key for key, words in vocabulary.items() if any(word in value for word in words)]
    if homepage and 'institutional' not in result:
        result.append('institutional')
    return result


def _exclude(data: Payload, url: str, reason: str, source: str) -> None:
    item = {'url': url[:4096], 'reason': reason, 'discovered_from': source}
    if item not in data['exclusions'] and len(data['exclusions']) < MAX_URLS:
        data['exclusions'].append(item)


def _enqueue(data: Payload, raw: str, source: str, kind: str = 'page') -> None:
    if not isinstance(raw, str) or len(raw) > 4096:
        return
    try:
        url = _url(urljoin(source, raw))
    except GateError:
        _exclude(data, raw, 'invalid_or_nonpublic_url', source)
        return
    if _origin(url) != data['origin']:
        _exclude(data, url, 'unconfirmed_origin', source)
        return
    if url in data['visited'] or any(item['url'] == url for item in data['queue'] + data.get('budget_deferred', [])):
        return
    if len(data['visited']) + len(data['queue']) >= data['limits']['max_urls']:
        if 'url_limit' not in data['limitations']:
            data['limitations'].append('url_limit')
        deferred = data.setdefault('budget_deferred', [])
        if len(deferred) < MAX_COVERAGE_BUDGET:
            deferred.append({'url': url, 'kind': kind, 'discovered_from': source})
        else:
            if 'frontier_storage_limit' not in data['limitations']:
                data['limitations'].append('frontier_storage_limit')
        _exclude(data, url, 'url_limit', source)
        return
    data['queue'].append({'url': url, 'kind': kind, 'discovered_from': source})


def expand_research_budget(store: Store, research_id: str, max_urls: int) -> Record:
    """Explicitly expand this run's finite coverage budget and requeue known URLs.

    No requests are performed here. Transport/robots/page-time limits stay intact.
    Legacy url_limit exclusions are recoverable without rereading their sitemap.
    """
    if type(max_urls) is not int or not MAX_URLS <= max_urls <= MAX_COVERAGE_BUDGET:
        raise GateError('invalid_research_budget')
    owner = uuid4().hex
    if not store.acquire_lease('research:' + research_id, owner, now_utc(), 120):
        raise GateError('research_in_progress')
    try:
        with store.transaction():
            run = store.get('analysis', research_id)
            if not run or run.data.get('type') != 'research_run':
                raise GateError('research_required')
            data = run.data
            _validate_research_subject(store, data)
            if max_urls < data['limits']['max_urls']:
                raise GateError('invalid_research_budget')
            data['limits']['max_urls'] = max_urls
            deferred = data.get('budget_deferred', [])
            # 0.4 pre-fix snapshots only stored these as exclusions. Preserve
            # those diagnostics while recovering their still-known URLs.
            legacy = [dict(item, kind='sitemap' if urlsplit(item['url']).path.endswith('.xml') else 'page')
                      for item in data['exclusions'] if item['reason'] == 'url_limit']
            data['budget_deferred'] = []
            for item in deferred + legacy:
                _enqueue(data, item['url'], item['discovered_from'], item['kind'])
            if not data['budget_deferred']:
                data['limitations'] = [code for code in data['limitations'] if code != 'url_limit']
            if data['queue'] and data['status'] != 'blocked':
                data['status'] = 'collecting'
            data['updated_at'] = now_utc()
            return store.put('analysis', run.id, data, run.revision)
    finally:
        store.release_lease('research:' + research_id, owner)


def _coverage(store: Store, data: Payload, stop_reason: str | None = None) -> Payload:
    pages = [store.get('analysis', id).data for id in data['page_ids']]
    read = [page for page in pages if page['status'] == 'read']
    covered = sorted({category for page in read for category in page['categories']})
    limitations = list(data['limitations'])
    resolved = {page['url'] for page in read}
    for code in ('document_reader_required', 'rendering_required'):
        if not any(page['status'] == code and page['url'] not in resolved for page in pages):
            limitations = [item for item in limitations if item != code]
    if stop_reason:
        limitations.append(stop_reason)
    return {'pages_read': len(read), 'pages_saved': len(pages), 'pending': len(data['queue']) + len(data.get('budget_deferred', [])),
            'budget_deferred': len(data.get('budget_deferred', [])),
            'deferred': sum(bool(item.get('retry_after') and utc(item['retry_after']) > utc(now_utc())) for item in data['queue']),
            'errors': len(data['errors']), 'excluded': len(data['exclusions']),
            'categories_covered': covered, 'categories_missing': [key for key in CATEGORIES if key not in covered],
            'known_frontier_complete': not data['queue'] and not data.get('budget_deferred') and not data['errors']
                and 'url_limit' not in limitations and 'frontier_storage_limit' not in limitations,
            'complete': not data['queue'] and not data.get('budget_deferred') and not data['errors'] and not limitations,
            'limitations': list(dict.fromkeys(limitations)), 'limits': data['limits']}


def _source_date(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise GateError('invalid_source_date')
    from datetime import date
    try:
        if len(value) == 10:
            date.fromisoformat(value)
        else:
            utc(value)
    except (GateError, ValueError):
        raise GateError('invalid_source_date') from None
    return value


def record_research_evidence(store: Store, research_id: str, items: list[Payload], source_kind: str, evidence_id: str) -> Record:
    """Persist actual host-read text or search results, not a claim of extraction.

    Each item requires url/title/text/source/collected_at; published_at is optional.
    source identifies the actual host tool/reference and evidence_id its result.
    Accept up to 20 items of up to 50k characters. Only external_news permits a
    different public origin; empty news results record that a real search ran.
    Call only after invoking the host tool. This API cannot certify tool execution.
    """
    if source_kind not in {'external_news', 'rendered_page', 'document'} or not isinstance(evidence_id, str) or not evidence_id.strip() or len(evidence_id) > 500:
        raise GateError('research_evidence_required')
    if not isinstance(items, list) or len(items) > 20 or (not items and source_kind != 'external_news'):
        raise GateError('invalid_research_evidence')
    run = store.get('analysis', research_id)
    if not run or run.data.get('type') != 'research_run':
        raise GateError('research_required')
    _validate_research_subject(store, run.data)
    owner = uuid4().hex
    if not store.acquire_lease('research:' + research_id, owner, now_utc(), 120):
        raise GateError('research_in_progress')
    try:
        prepared = []
        for item in items:
            if not isinstance(item, dict) or any(not isinstance(item.get(key), str) or not item[key].strip() for key in ('url', 'title', 'text', 'source', 'collected_at')):
                raise GateError('research_evidence_source_required')
            if len(item['text']) > MAX_TEXT or len(item['title']) > 500 or len(item['source']) > 1000:
                raise GateError('research_evidence_limit')
            utc(item['collected_at'])
            url = public_url(item['url'])
            if source_kind != 'external_news' and _origin(url) != run.data['origin']:
                raise GateError('unconfirmed_evidence_origin')
            if source_kind != 'external_news' and run.data['robots_text'] is not None:
                robots = RobotFileParser()
                robots.parse(run.data['robots_text'].splitlines())
                if not robots.can_fetch(USER_AGENT, url):
                    raise GateError('robots_disallowed')
            prepared.append({'url': url, 'title': item['title'], 'text': item['text'], 'source': item['source'],
                             'collected_at': item['collected_at'], 'published_at': _source_date(item.get('published_at')),
                             'sha256': sha256(item['text'].encode('utf-8')).hexdigest()})
        record_id = research_id + '-host-' + sha256((source_kind + ':' + evidence_id).encode()).hexdigest()[:24]
        with store.transaction():
            run = store.get('analysis', research_id)
            _validate_research_subject(store, run.data)
            existing = store.get('analysis', record_id)
            if existing:
                if existing.data.get('items') != prepared:
                    raise GateError('research_evidence_conflict')
                return existing
            record = store.put('analysis', record_id, {'type': 'research_host_evidence', 'research_id': research_id,
                'subject_id': run.data['subject_id'], 'source_kind': source_kind, 'evidence_id': evidence_id,
                'trust': 'untrusted_external_data', 'recorded_at': now_utc(), 'items': prepared}, None)
            data = run.data
            data.setdefault('host_evidence_ids', []).append(record_id)
            for index, item in enumerate(prepared):
                page_id = record_id + '-' + str(index)
                store.put('analysis', page_id, dict(item, type='research_page', research_id=research_id,
                    subject_id=data['subject_id'], requested_url=item['url'], discovered_from=evidence_id,
                    status='read', trust='untrusted_external_data', host_evidence_id=evidence_id,
                    source_kind=source_kind, content_type='host_extracted_text', text_sha256=item['sha256'],
                    categories=['news'] if source_kind == 'external_news' else _categories(item['url'], item['title'], item['url'] == data['website'])), None)
                data['page_ids'].append(page_id)
                # The host actually read this URL; retain placeholders and errors
                # as history, but do not fetch the same queued URL again.
                if source_kind != 'external_news':
                    data['queue'] = [entry for entry in data['queue'] if entry['url'] != item['url'] or entry['kind'] == 'robots']
                    data['errors'] = [entry for entry in data['errors'] if entry['url'] != item['url']]
                    if item['url'] not in data['visited']:
                        data['visited'].append(item['url'])
            if source_kind == 'external_news':
                data['external_news_search'] = {'evidence_id': evidence_id, 'record_id': record.id, 'recorded_at': now_utc()}
                data['limitations'] = [value for value in data['limitations'] if value != 'external_news_not_searched']
            data['updated_at'] = now_utc()
            store.put('analysis', run.id, data, run.revision)
            return record
    finally:
        store.release_lease('research:' + research_id, owner)


def _response(result: object, requested: str, origin: str) -> Payload:
    if not isinstance(result, dict) or type(result.get('status')) is not int:
        raise GateError('invalid_fetch_result')
    final = _url(result.get('url', ''))
    if _origin(final) != origin:
        raise GateError('unconfirmed_redirect_origin')
    text = result.get('text', '')
    if not isinstance(text, str) or len(text.encode('utf-8')) > MAX_BODY * 4:
        raise GateError('response_too_large')
    body = result.get('body', '')
    if not isinstance(body, str) or len(body) > (MAX_BODY + 2) // 3 * 4:
        raise GateError('response_too_large')
    try:
        raw = base64.b64decode(body, validate=True) if body else text.encode('utf-8')
    except (ValueError, binascii.Error):
        raise GateError('invalid_fetch_result') from None
    return dict(result, url=final, text=text, sha256=sha256(raw).hexdigest(),
                content_type=str(result.get('content_type', '')).split(';', 1)[0].lower())


def crawl_batch(store: Store, research_id: str, max_pages: int = 20, max_seconds: int = 30, fetcher=None) -> Payload:
    """Process a durable frontier with one bounded public request at a time.

    fetcher(url: str) -> Payload is for deterministic fixtures only, returning
    {url: str, status: int, content_type: str, text: str, body: base64 str}.
    Production defaults to fetch_public; host render/PDF evidence is not inferred.
    The time budget is checked between requests (each request also has a timeout).
    """
    if type(max_pages) is not int or not 1 <= max_pages <= 100 or type(max_seconds) is not int or not 1 <= max_seconds <= 120:
        raise GateError('invalid_research_limits')
    run = store.get('analysis', research_id)
    if not run or run.data.get('type') != 'research_run':
        raise GateError('research_required')
    _validate_research_subject(store, run.data)
    owner = uuid4().hex
    if not store.acquire_lease('research:' + research_id, owner, now_utc(), max_seconds + 90):
        raise GateError('research_in_progress')
    started, count, requests, stop_reason = time.monotonic(), 0, 0, None
    try:
        while True:
            run = store.get('analysis', research_id)
            data = run.data
            if not data['queue']:
                break
            if count >= max_pages or requests >= max_pages + 10:
                stop_reason = 'batch_page_limit'
                break
            if time.monotonic() - started >= max_seconds:
                stop_reason = 'batch_time_limit'
                break
            _validate_research_subject(store, data)
            if data['queue'][0].get('terminal'):
                stop_reason = 'robots_unavailable'
                break
            ready = next((index for index, entry in enumerate(data['queue'])
                          if not entry.get('retry_after') or utc(entry['retry_after']) <= utc(now_utc())), None)
            if ready is None:
                stop_reason = 'retry_deferred'
                break
            item = data['queue'][ready]
            url, kind = item['url'], item['kind']
            robots = None
            if kind != 'robots':
                if data['robots_text'] is None:
                    raise GateError('robots_required')
                robots = RobotFileParser()
                robots.parse(data['robots_text'].splitlines())
                if not robots.can_fetch(USER_AGENT, url):
                    with store.transaction():
                        data['queue'].pop(ready)
                        data['visited'].append(url)
                        _exclude(data, url, 'robots_disallowed', item['discovered_from'])
                        store.put('analysis', run.id, data, run.revision)
                    continue
                try:
                    delay = _robots_delay(robots)
                except GateError as error:
                    diagnostic = {'url': data['origin'] + '/robots.txt', 'code': error.code,
                                  'observed_at': now_utc(), 'terminal': True}
                    data['errors'] = [entry for entry in data['errors'] if entry['url'] != diagnostic['url']] + [diagnostic]
                    data['status'] = 'blocked'
                    store.put('analysis', run.id, data, run.revision)
                    stop_reason = error.code
                    break
                if data.get('last_request_at') and (utc(now_utc()) - utc(data['last_request_at'])).total_seconds() < delay:
                    stop_reason = 'robots_delay'
                    break
            try:
                requests += 1
                result = _response(fetcher(url) if fetcher else fetch_public(url, allowed_origin=data['origin'],
                                   url_allowed=(lambda target: robots.can_fetch(USER_AGENT, target)) if robots else None), url, data['origin'])
                _validate_research_subject(store, data)
                if result['status'] not in range(200, 300) and not (kind in {'robots', 'sitemap'} and result['status'] in {404, 410}):
                    raise GateError('http_' + str(result['status']))
                # Parse before committing so a crash cannot lose a frontier item.
                parser = None
                if kind == 'robots':
                    if result['status'] in {404, 410}:
                        data['robots_text'] = ''
                    elif result['content_type'] not in {'text/plain', ''}:
                        raise GateError('invalid_robots')
                    else:
                        policy = RobotFileParser()
                        policy.parse(result['text'].splitlines())
                        _robots_delay(policy)
                        data['robots_text'] = result['text']
                elif kind == 'sitemap' and result['status'] in range(200, 300):
                    if '<!DOCTYPE' in result['text'].upper() or '<!ENTITY' in result['text'].upper():
                        raise GateError('unsafe_sitemap')
                    try:
                        tree = ET.fromstring(result['text'])
                    except ET.ParseError:
                        raise GateError('invalid_sitemap') from None
                    if tree.tag.rsplit('}', 1)[-1] not in {'sitemapindex', 'urlset'}:
                        raise GateError('invalid_sitemap')
                elif kind == 'page' and result['content_type'] in {'text/html', 'application/xhtml+xml'}:
                    parser = _HTML()
                    parser.feed(result['text'])
                with store.transaction():
                    _validate_research_subject(store, data)
                    data['queue'].pop(ready)
                    data['visited'].append(url)
                    data['last_request_at'] = now_utc()
                    data['errors'] = [error for error in data['errors'] if error['url'] != url]
                    if kind == 'robots':
                        robots = RobotFileParser()
                        robots.parse(data['robots_text'].splitlines())
                        for sitemap in robots.site_maps() or []:
                            _enqueue(data, sitemap, url, 'sitemap')
                    elif kind == 'sitemap' and result['status'] in range(200, 300):
                        is_index = tree.tag.rsplit('}', 1)[-1] == 'sitemapindex'
                        for location in tree.iter():
                            if location.tag.rsplit('}', 1)[-1] == 'loc' and location.text:
                                _enqueue(data, location.text.strip(), url, 'sitemap' if is_index else 'page')
                    elif kind == 'page':
                        text = ' '.join(' '.join(parser.text).split()) if parser else result['text'] if result['content_type'] == 'text/plain' else ''
                        title = ' '.join(parser.title) if parser else ''
                        status = 'read'
                        if result['content_type'] not in {'text/plain', 'text/html', 'application/xhtml+xml'}:
                            status = 'document_reader_required'
                        elif len(text) < 10:
                            status = 'rendering_required'
                        if status != 'read' and status not in data['limitations']:
                            data['limitations'].append(status)
                        if len(text) > MAX_TEXT and 'text_truncated' not in data['limitations']:
                            data['limitations'].append('text_truncated')
                        page = {'type': 'research_page', 'research_id': run.id, 'subject_id': data['subject_id'],
                                'url': result['url'], 'requested_url': url, 'discovered_from': item['discovered_from'],
                                'collected_at': now_utc(), 'published_at': parser.published_at if parser else None,
                                'sha256': result['sha256'],
                                'text_sha256': sha256(text.encode('utf-8')).hexdigest(),
                                'text': text[:MAX_TEXT], 'title': title[:500], 'content_type': result['content_type'],
                                'http_status': result['status'], 'status': status, 'trust': 'untrusted_external_data',
                                'categories': _categories(result['url'], title, url == data['website'])}
                        page_id = run.id + '-page-' + sha256(url.encode()).hexdigest()[:24]
                        store.put('analysis', page_id, page, None)
                        data['page_ids'].append(page_id)
                        count += 1
                        if parser:
                            for link in parser.links:
                                _enqueue(data, link, result['url'])
                    if kind in {'robots', 'sitemap'}:
                        data['metadata_sources'].append({'url': result['url'], 'requested_url': url,
                            'kind': kind, 'discovered_from': item['discovered_from'], 'collected_at': now_utc(),
                            'sha256': result['sha256'], 'http_status': result['status'], 'content_type': result['content_type']})
                    data['updated_at'] = now_utc()
                    data['status'] = 'collecting' if data['queue'] else 'collected_with_limitations'
                    store.put('analysis', run.id, data, run.revision)
            except (GateError, OSError, ValueError) as error:
                code = error.code if isinstance(error, GateError) else 'fetch_failed'
                if code in {'research_identity_review_required', 'selected_account_required', 'partner_identity_mismatch'}:
                    raise
                attempts = item.get('attempts', 0) + 1
                transient = code in {'network_unavailable', 'connection_unavailable', 'dns_unavailable',
                                     'request_time_limit', 'fetch_failed', 'http_408', 'http_429'} or code.startswith('http_5')
                terminal = not transient or attempts >= MAX_ATTEMPTS
                retry_after = (utc(now_utc()) + timedelta(seconds=RETRY_SECONDS)).isoformat() if not terminal and kind != 'robots' else None
                data['errors'] = [entry for entry in data['errors'] if entry['url'] != url]
                data['errors'].append({'url': url, 'code': code, 'observed_at': now_utc(),
                                       'attempts': attempts, 'terminal': terminal, 'retry_after': retry_after})
                data['last_request_at'] = now_utc()
                if kind == 'robots':
                    # Robots remain a strict prerequisite; never continue under
                    # an unavailable/invalid policy, including after retry cap.
                    data['queue'][ready] = dict(item, attempts=attempts, terminal=terminal)
                    data['status'] = 'blocked'
                else:
                    data['queue'].pop(ready)
                    if terminal:
                        if url not in data['visited']:
                            data['visited'].append(url)
                        _exclude(data, url, 'failed:' + code, item['discovered_from'])
                    else:
                        data['queue'].append(dict(item, attempts=attempts, retry_after=retry_after))
                    data['status'] = 'collecting_with_errors'
                store.put('analysis', run.id, data, run.revision)
                if kind == 'robots':
                    stop_reason = 'robots_unavailable' if terminal else 'retry_required'
                    break
                # Defer transient failures and retire permanent/exhausted URLs;
                # neither may starve later work in the known frontier.
        current = store.get('analysis', research_id)
        _validate_research_subject(store, current.data)
        return {'research_id': research_id, 'status': current.data['status'],
                'coverage': _coverage(store, current.data, stop_reason),
                'errors': current.data['errors'], 'exclusions': current.data['exclusions']}
    finally:
        store.release_lease('research:' + research_id, owner)


def research_context(store: Store, subject_id: str, limit: int = 8) -> Payload:
    """Return bounded sourced excerpts as untrusted data, never instructions."""
    if type(limit) is not int or not 1 <= limit <= 20:
        raise GateError('invalid_research_limit')
    purpose = 'partner' if subject_id == store.scope.partner_id else 'prospect'
    _subject(store, subject_id, purpose)
    runs = [run for run in store.list('analysis') if run.data.get('type') == 'research_run' and run.data.get('subject_id') == subject_id]
    runs.sort(key=lambda run: run.data['created_at'], reverse=True)
    latest = runs[0] if runs else None
    if latest:
        _validate_research_subject(store, latest.data)
    pages = [store.get('analysis', id) for id in latest.data['page_ids']] if latest else []
    read = [page for page in pages if page.data['status'] == 'read']
    # Prioritize dated news and recent host evidence inside the bounded context.
    read.sort(key=lambda page: (bool(page.data.get('published_at') and 'news' in page.data['categories']),
                               page.data['collected_at']), reverse=True)
    evidence = [{key: page.data[key] for key in ('url', 'title', 'collected_at', 'published_at', 'sha256', 'categories')} |
                {'record_id': page.id, 'excerpt': page.data['text'][:1500],
                 'source': page.data.get('source', page.data['url']),
                 'host_evidence_id': page.data.get('host_evidence_id')} for page in read[:limit]]
    news = [item for item in evidence if 'news' in item['categories'] and item['published_at']]
    searched = latest.data.get('external_news_search') if latest else None
    external_dated = any(page.data.get('source_kind') == 'external_news' and page.data.get('published_at') for page in read)
    return {'subject_id': subject_id, 'trust': 'untrusted_external_data', 'evidence': evidence,
            'dated_news': news, 'external_news': {'status': ('searched_with_dated_results' if external_dated else 'searched_no_dated_results') if searched else 'not_searched',
                                                'search_evidence': searched, 'reason': None if searched else 'search_tool_not_invoked'},
            'coverage': _coverage(store, latest.data) if latest else {'pages_read': 0, 'complete': False, 'limitations': ['research_not_started']},
            'history_preserved': len(runs) > 1}

"""Bounded public HTTP transport, with DNS answers pinned to the actual socket.

No proxy, cookies, authentication, scripts, renderer or document extraction. DNS
validation and connecting are one operation: a second hostname lookup must never
choose a different (possibly private) address after validation.
"""
from __future__ import annotations

import base64
import http.client
import io
import ipaddress
import os
import socket
import ssl
import time
import zlib
from urllib.parse import urljoin, urlsplit, urlunsplit

from .models import GateError, Payload

MAX_BODY = 1_048_576
TIMEOUT = 5
MAX_REDIRECTS = 5
MAX_FETCH_SECONDS = 20
USER_AGENT = 'ACLADResearch/0.4'
_SYSTEM_CA_BUNDLE = '/etc/ssl/cert.pem'


def _tls_context() -> ssl.SSLContext:
    """Retain verified default TLS, recovering an undiscovered OS trust bundle.

    Some Python distributions have no discoverable OpenSSL CA defaults. Only
    that unconfigured empty-store case may use this fixed operating-system
    bundle. Explicit environment configuration, including empty values, wins.
    """
    context = ssl.create_default_context()
    paths = ssl.get_default_verify_paths()
    if (not any(name in os.environ for name in ('SSL_CERT_FILE', 'SSL_CERT_DIR'))
            and not paths.cafile and not paths.capath
            and context.cert_store_stats()['x509_ca'] == 0
            and os.path.isfile(_SYSTEM_CA_BUNDLE)):
        context.load_verify_locations(cafile=_SYSTEM_CA_BUNDLE)
    return context


def _global_address(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
        if not address.is_global or address.is_multicast or address.is_reserved:
            return False
        if isinstance(address, ipaddress.IPv6Address):
            # Reject transition mechanisms with embedded destinations. In
            # particular NAT64 can otherwise make a loopback IPv4 appear global.
            if address.ipv4_mapped or address.sixtofour or address.teredo:
                return False
            if address in ipaddress.ip_network('64:ff9b::/96') or address in ipaddress.ip_network('64:ff9b:1::/48'):
                return False
        return True
    except ValueError:
        return False


def _url(url: str) -> str:
    if not isinstance(url, str) or len(url) > 4096 or any(ord(c) <= 32 or ord(c) == 127 for c in url) or '\\' in url:
        raise GateError('invalid_public_url')
    try:
        parts = urlsplit(url)
        if parts.scheme.lower() not in {'http', 'https'} or not parts.hostname or parts.username is not None or parts.password is not None:
            raise ValueError()
        hostname = parts.hostname.encode('idna').decode('ascii').lower().rstrip('.')
        if hostname == 'localhost' or hostname.endswith(('.localhost', '.local', '.internal', '.home', '.lan')) or '%' in hostname:
            raise ValueError()
        try:
            literal = ipaddress.ip_address(hostname)
        except ValueError:
            literal = None
        if literal is not None and not _global_address(hostname):
            raise ValueError()
        port = parts.port
        if port not in (None, 80 if parts.scheme.lower() == 'http' else 443):
            raise ValueError()
        netloc = f'[{hostname}]' if ':' in hostname else hostname
        # Default ports are canonicalized, fragments never reach the server.
        return urlunsplit((parts.scheme.lower(), netloc, parts.path or '/', parts.query, ''))
    except (ValueError, UnicodeError):
        raise GateError('invalid_public_url') from None


def _addresses(url: str, resolver=None):
    parts = urlsplit(url)
    port = 443 if parts.scheme == 'https' else 80
    try:
        answers = (resolver or socket.getaddrinfo)(parts.hostname, port, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except OSError:
        raise GateError('dns_unavailable') from None
    if not answers or any(not _global_address(item[4][0]) for item in answers):
        raise GateError('public_address_required')
    return answers


def public_url(url: str, resolver=None) -> str:
    """Normalize HTTP(S) URL and reject any nonpublic DNS answer (all answers)."""
    normalized = _url(url)
    _addresses(normalized, resolver)
    return normalized


class _DeadlineReader(io.RawIOBase):
    def __init__(self, connection):
        super().__init__()
        self.connection = connection

    def readable(self):
        return True

    def readinto(self, buffer):
        self.connection.remaining()
        return self.connection.raw.recv_into(buffer)

    def close(self):
        if not self.closed:
            super().close()
            self.connection.release_file()


class _DeadlineSocket:
    """Enforce an absolute deadline even while headers/body trickle in."""
    def __init__(self, raw, deadline):
        self.raw = raw
        self.deadline = deadline
        self.file_refs = 0
        self.closed = False

    def remaining(self):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise GateError('request_time_limit')
        self.raw.settimeout(min(TIMEOUT, remaining))

    def makefile(self, mode):
        if mode != 'rb':
            raise GateError('invalid_transport_mode')
        self.file_refs += 1
        return io.BufferedReader(_DeadlineReader(self))

    def sendall(self, data):
        self.remaining()
        self.raw.sendall(data)

    def close(self):
        if not self.closed:
            self.closed = True
            if not self.file_refs:
                self.raw.close()

    def release_file(self):
        self.file_refs -= 1
        if self.closed and not self.file_refs:
            self.raw.close()

    def __getattr__(self, name):
        return getattr(self.raw, name)


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, host, port, addresses, timeout):
        super().__init__(host, port=port, timeout=timeout)
        self.addresses = addresses
        self.deadline = time.monotonic() + MAX_FETCH_SECONDS

    def _connect_socket(self):
        for family, socktype, proto, _, address in self.addresses[:2]:
            remaining = self.deadline - time.monotonic()
            if remaining <= 0:
                raise GateError('request_time_limit')
            connection = socket.socket(family, socktype, proto)
            try:
                connection.settimeout(min(self.timeout, remaining))
                connection.connect(address)
                return connection
            except OSError:
                connection.close()
        raise GateError('connection_unavailable')

    def connect(self):
        self.sock = _DeadlineSocket(self._connect_socket(), self.deadline)


class _PinnedHTTPSConnection(_PinnedHTTPConnection):
    def connect(self):
        self.sock = self._connect_socket()
        # Certificate verification and SNI use the original hostname while the
        # connected socket is the exact validated address; no DNS occurs here.
        try:
            self.sock = _tls_context().wrap_socket(self.sock, server_hostname=self.host)
            self.sock = _DeadlineSocket(self.sock, self.deadline)
        except BaseException:
            self.close()
            raise


def fetch_public(url: str, *, allowed_origin: str | None = None, url_allowed=None) -> Payload:
    """Fetch at most 1 MiB over pinned HTTP(S), following at most five redirects.

    Return JSON-safe {url, status, content_type, text, body, extraction}; body is
    base64, text is decoded only for supported text media. Errors fail closed.
    Each redirect, including a same-host redirect, resolves and pins anew.
    """
    current = _url(url)
    deadline = time.monotonic() + MAX_FETCH_SECONDS
    for redirects in range(MAX_REDIRECTS + 1):
        if allowed_origin and (urlsplit(current).scheme + '://' + urlsplit(current).netloc) != allowed_origin:
            raise GateError('unconfirmed_redirect_origin')
        if url_allowed is not None and not url_allowed(current):
            raise GateError('robots_disallowed_redirect')
        answers = _addresses(current)
        parts = urlsplit(current)
        connection_type = _PinnedHTTPSConnection if parts.scheme == 'https' else _PinnedHTTPConnection
        connection = connection_type(parts.hostname, 443 if parts.scheme == 'https' else 80, answers, TIMEOUT)
        connection.deadline = deadline
        try:
            path = parts.path + (('?' + parts.query) if parts.query else '')
            connection.request('GET', path, headers={'User-Agent': USER_AGENT, 'Accept-Encoding': 'identity', 'Accept': 'text/html,text/plain,application/xml;q=0.9,*/*;q=0.1'})
            response = connection.getresponse()
            if response.status in {301, 302, 303, 307, 308}:
                target = response.getheader('Location')
                if not target or redirects == MAX_REDIRECTS:
                    raise GateError('redirect_limit')
                current = _url(urljoin(current, target))
                continue
            encoding = (response.getheader('Content-Encoding', 'identity') or 'identity').strip().lower()
            if encoding not in ('identity', 'gzip'):
                raise GateError('unsupported_content_encoding')
            raw = response.read(MAX_BODY + 1)
            if len(raw) > MAX_BODY:
                raise GateError('response_too_large')
            if encoding == 'gzip':
                # Bound both network bytes and decoded bytes. A single member
                # must finish with a valid checksum; never accept a truncated
                # stream, concatenated members, or silently ignored trailing data.
                decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
                try:
                    raw = decoder.decompress(raw, MAX_BODY + 1)
                except zlib.error:
                    raise GateError('invalid_compressed_response') from None
                if len(raw) > MAX_BODY:
                    raise GateError('response_too_large')
                if not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
                    raise GateError('invalid_compressed_response')
            content_type = (response.getheader('Content-Type', '') or '').split(';', 1)[0].strip().lower()
            supported = content_type.startswith('text/') or content_type in {'application/xml', 'application/xhtml+xml', 'application/rss+xml', 'application/atom+xml'}
            text = ''
            if supported:
                header = response.getheader('Content-Type', '') or ''
                charset = 'utf-8'
                for parameter in header.split(';')[1:]:
                    if parameter.strip().lower().startswith('charset='):
                        charset = parameter.split('=', 1)[1].strip(' \"\'')
                try:
                    text = raw.decode(charset, errors='replace')
                except LookupError:
                    text = raw.decode('utf-8', errors='replace')
            return {'url': current, 'status': response.status, 'content_type': content_type,
                    'text': text, 'body': base64.b64encode(raw).decode('ascii'),
                    'extraction': 'text' if supported else 'unsupported'}
        except (OSError, http.client.HTTPException, UnicodeError):
            raise GateError('network_unavailable') from None
        finally:
            connection.close()
    raise GateError('redirect_limit')

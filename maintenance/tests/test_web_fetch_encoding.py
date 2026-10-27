"""Bounded gzip decoding exercises real compressed bodies behind fake transport."""
import base64
import gzip
import random
import socket
import unittest
from unittest.mock import patch

from aclad.models import GateError
from aclad.web_fetch import MAX_BODY, fetch_public


class _Response:
    status = 200

    def __init__(self, body, encoding):
        self.body = body
        self.headers = {'content-type': 'text/html; charset=utf-8', 'content-encoding': encoding}

    def getheader(self, name, default=None):
        return self.headers.get(name.lower(), default)

    def read(self, limit):
        return self.body[:limit]


class GzipFetchTests(unittest.TestCase):
    def fetch(self, body, encoding='gzip'):
        response = _Response(body, encoding)
        addresses = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('8.8.8.8', 80))]
        with patch('aclad.web_fetch.socket.getaddrinfo', return_value=addresses), \
             patch('aclad.web_fetch._PinnedHTTPConnection') as transport:
            transport.return_value.getresponse.return_value = response
            return fetch_public('http://example.com')

    def test_valid_gzip_returns_decoded_text_and_body(self):
        raw = '<html>Pesquisa pública</html>'.encode('utf-8')
        output = self.fetch(gzip.compress(raw))
        self.assertEqual(output['status'], 200)
        self.assertEqual(output['text'], '<html>Pesquisa pública</html>')
        self.assertEqual(base64.b64decode(output['body']), raw)
        self.assertEqual(output['extraction'], 'text')

    def test_gzip_content_encoding_token_is_case_insensitive(self):
        output = self.fetch(gzip.compress(b'hello'), 'GZip')
        self.assertEqual(output['text'], 'hello')

    def test_decompressed_body_exactly_at_limit_succeeds(self):
        output = self.fetch(gzip.compress(b'x' * MAX_BODY))
        self.assertEqual(len(output['text']), MAX_BODY)

    def test_compressed_body_above_limit_is_rejected_before_decoding(self):
        compressed = gzip.compress(random.Random(13).randbytes(MAX_BODY + 1))
        self.assertGreater(len(compressed), MAX_BODY)
        with self.assertRaises(GateError) as caught:
            self.fetch(compressed)
        self.assertEqual(caught.exception.code, 'response_too_large')

    def test_decompression_bomb_cannot_exceed_decoded_limit(self):
        compressed = gzip.compress(b'x' * (MAX_BODY + 1))
        self.assertLess(len(compressed), MAX_BODY)
        with self.assertRaises(GateError) as caught:
            self.fetch(compressed)
        self.assertEqual(caught.exception.code, 'response_too_large')

    def test_truncated_and_checksum_invalid_gzip_are_rejected(self):
        compressed = gzip.compress(b'hello')
        for body in (compressed[:-5], compressed[:-1] + bytes([compressed[-1] ^ 1]), b'not gzip'):
            with self.subTest(body=body), self.assertRaises(GateError) as caught:
                self.fetch(body)
            self.assertEqual(caught.exception.code, 'invalid_compressed_response')

    def test_multiple_gzip_members_and_trailing_data_are_rejected(self):
        compressed = gzip.compress(b'hello')
        for body in (compressed + gzip.compress(b'world'), compressed + b'trailing'):
            with self.subTest(body=body), self.assertRaises(GateError) as caught:
                self.fetch(body)
            self.assertEqual(caught.exception.code, 'invalid_compressed_response')

    def test_unsupported_and_stacked_content_encodings_remain_rejected(self):
        for encoding in ('br', 'deflate', 'gzip, br', 'gzip, gzip'):
            with self.subTest(encoding=encoding), self.assertRaises(GateError) as caught:
                self.fetch(b'anything', encoding)
            self.assertEqual(caught.exception.code, 'unsupported_content_encoding')

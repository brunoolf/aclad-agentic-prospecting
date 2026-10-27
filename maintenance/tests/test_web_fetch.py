import socket
import unittest
from unittest.mock import patch

from aclad.models import GateError
from aclad.web_fetch import public_url, fetch_public, _PinnedHTTPConnection, _DeadlineSocket


def resolver(address):
    def resolve(host, port, *args, **kwargs):
        return [(socket.AF_INET6 if ':' in address else socket.AF_INET,
                 socket.SOCK_STREAM, 6, '', (address, port))]
    return resolve


class PublicWebTests(unittest.TestCase):
    def test_public_normalization_and_private_resolution(self):
        self.assertEqual(public_url('https://EXAMPLE.com/a#x', resolver('8.8.8.8')),
                         'https://example.com/a')
        for address in ('127.0.0.1', '10.1.2.3', '169.254.169.254', '::1', 'fc00::1',
                        '192.0.2.1', '224.0.0.1', 'ff02::1', '::ffff:127.0.0.1', '64:ff9b::7f00:1'):
            with self.subTest(address=address), self.assertRaises(GateError):
                public_url('https://example.com', resolver(address))

    def test_rejects_unsafe_url_forms_and_mixed_dns(self):
        for url in ('file:///etc/passwd', 'http://localhost', 'http://user:pass@example.com',
                    'https://example.com:22', 'https://example.com/\nX-Header: bad'):
            with self.subTest(url=url), self.assertRaises(GateError):
                public_url(url, resolver('8.8.8.8'))
        mixed = lambda *a, **k: resolver('8.8.8.8')(*a) + resolver('127.0.0.1')(*a)
        with self.assertRaises(GateError):
            public_url('https://example.com', mixed)

    def test_transport_connects_to_validated_ip_without_second_dns(self):
        with patch('aclad.web_fetch.socket.socket') as sock, patch('aclad.web_fetch.socket.getaddrinfo') as dns:
            connection = _PinnedHTTPConnection('example.com', 80,
                                               resolver('8.8.8.8')('example.com', 80), 5)
            connection.connect()
            sock.return_value.connect.assert_called_once_with(('8.8.8.8', 80))
            dns.assert_not_called()

    def test_slow_trickle_cannot_extend_absolute_socket_deadline(self):
        raw = unittest.mock.Mock()
        raw.recv_into.return_value = 1
        connection = _DeadlineSocket(raw, deadline=20)
        stream = connection.makefile('rb')
        with patch('aclad.web_fetch.time.monotonic', side_effect=[1, 21]):
            self.assertEqual(stream.read(1), b'\x00')
            with self.assertRaisesRegex(GateError, 'request time limit'):
                stream.read(1)
        self.assertEqual(raw.recv_into.call_count, 1)
        stream.close()

    def test_connection_close_response_remains_readable_until_body_consumed(self):
        wire = bytearray(b'HTTP/1.1 200 OK\r\nConnection: close\r\nContent-Type: text/plain\r\nContent-Length: 11\r\n\r\nhello world')
        closed = []
        def receive(buffer):
            if closed:
                raise OSError('socket already closed')
            available = wire.index(b'\r\n\r\n') + 4 if wire.startswith(b'HTTP/') else len(wire)
            count = min(len(buffer), available)
            buffer[:count] = wire[:count]
            del wire[:count]
            return count
        with patch('aclad.web_fetch.socket.socket') as sock, \
             patch('aclad.web_fetch.socket.getaddrinfo', resolver('8.8.8.8')):
            sock.return_value.recv_into.side_effect = receive
            sock.return_value.close.side_effect = lambda: closed.append(True)
            result = fetch_public('http://example.com')
            self.assertEqual(result['text'], 'hello world')
            sock.return_value.close.assert_called_once()

    def test_redirect_to_private_network_is_rejected_before_connection(self):
        response = unittest.mock.Mock(status=302)
        response.getheader.side_effect = lambda key, default=None: {'Location': 'http://127.0.0.1/admin'}.get(key, default)
        with patch('aclad.web_fetch.socket.getaddrinfo', resolver('8.8.8.8')), \
             patch('aclad.web_fetch._PinnedHTTPConnection') as connection:
            connection.return_value.getresponse.return_value = response
            with self.assertRaises(GateError):
                fetch_public('http://example.com')
            self.assertEqual(connection.call_count, 1)

    def test_bounded_binary_result_does_not_pretend_pdf_extraction(self):
        response = unittest.mock.Mock(status=200)
        response.getheader.side_effect = lambda key, default=None: {'Content-Type': 'application/pdf'}.get(key, default)
        response.read.return_value = b'%PDF-1.7 binary'
        with patch('aclad.web_fetch.socket.getaddrinfo', resolver('8.8.8.8')), \
             patch('aclad.web_fetch._PinnedHTTPConnection') as connection:
            connection.return_value.getresponse.return_value = response
            result = fetch_public('http://example.com/report.pdf')
            self.assertEqual(result['text'], '')
            self.assertEqual(result['body'], 'JVBERi0xLjcgYmluYXJ5')
            self.assertEqual(result['extraction'], 'unsupported')
            response.read.assert_called_once_with(1_048_577)

    def test_oversized_response_is_rejected(self):
        response = unittest.mock.Mock(status=200)
        response.getheader.return_value = None
        response.read.return_value = b'x' * 1_048_577
        with patch('aclad.web_fetch.socket.getaddrinfo', resolver('8.8.8.8')), \
             patch('aclad.web_fetch._PinnedHTTPConnection') as connection:
            connection.return_value.getresponse.return_value = response
            with self.assertRaisesRegex(GateError, 'response too large'):
                fetch_public('http://example.com')

    def test_crawler_origin_and_robots_policy_apply_before_redirect_fetch(self):
        for target, policy in (('http://different.example/', None),
                               ('http://example.com/private', lambda url: '/private' not in url)):
            response = unittest.mock.Mock(status=302)
            response.getheader.side_effect = lambda key, default=None: target if key == 'Location' else default
            with self.subTest(target=target), patch('aclad.web_fetch.socket.getaddrinfo', resolver('8.8.8.8')), \
                 patch('aclad.web_fetch._PinnedHTTPConnection') as connection:
                connection.return_value.getresponse.return_value = response
                with self.assertRaises(GateError):
                    fetch_public('http://example.com', allowed_origin='http://example.com', url_allowed=policy)
                self.assertEqual(connection.call_count, 1)

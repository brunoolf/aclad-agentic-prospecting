"""System CA fallback preserves verified TLS and explicit operator configuration."""
import os
from pathlib import Path
import ssl
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from aclad import web_fetch

# Synthetic public test identity; never used by a provider or account.
TEST_CERT = """-----BEGIN CERTIFICATE-----
MIIDRzCCAi+gAwIBAgIUQ5aJ9Zrhg1tiVDJziKQRsanrIBAwDQYJKoZIhvcNAQEL
BQAwGzEZMBcGA1UEAwwQcmVzZWFyY2guZXhhbXBsZTAgFw0yNjEwMjcxMDE5MDNa
GA8yMTI2MTAwMzEwMTkwM1owGzEZMBcGA1UEAwwQcmVzZWFyY2guZXhhbXBsZTCC
ASIwDQYJKoZIhvcNAQEBBQADggEPADCCAQoCggEBALWUM5Vyx6R0Gosa8L5KgUCP
5fpnXU1MEzqxsMIuhZ2JaGTqTVI2r3zxowZDaSdJK8JCM939YWpGReph4WPc/ovC
uFZrjWpGlPNqTd0DNNQQ/5dfkn5PcpEjWdC4CECL9eSfLXVnkyFl6/DT07z8e50r
bBWcXveGnsX3nJe671Ky41IzCcRL+jpBl6F0vEtNCWifUOTunRBYX8dcAUi4SYT0
mEWgGasHa5WUjwekCf09eaelOvJYRjl3yhOptXJooAPnUx35XPpMiPa1XpJBnUHS
BSO1l+Cvi+pOcNvOrhnC22yz8W5SF9HnBKMC51kOoN9PAWTn+EQWqL5EmgUfN3UC
AwEAAaOBgDB+MB0GA1UdDgQWBBRAFsQ+2sYx0GXx7Y4++SNnQpDrCzAfBgNVHSME
GDAWgBRAFsQ+2sYx0GXx7Y4++SNnQpDrCzAbBgNVHREEFDASghByZXNlYXJjaC5l
eGFtcGxlMA4GA1UdDwEB/wQEAwICpDAPBgNVHRMBAf8EBTADAQH/MA0GCSqGSIb3
DQEBCwUAA4IBAQCvnZSl0eu3gUova9i4aq76d8EZ8cM3p31Hjy1Y2BokVs4SFwLU
vSBScQm+iaofq7IHNYnLadVVMVQxyb45+eu/LaIWIp2qDFMk8MCiEfbLqjyeg5dW
VzDHsvn1TNTAXXnRzgqbmcbIPGgfv51FuC+PRcFgjykG3Ms7fDkmeXS4hA8DsWKj
Ku444SoChrwD2DZSohYCu65SPtEF9zfiwefdRMJk1/Gcq1rkVvHLWNEwBZl7Ym96
MYYrnh36dL0eeobdTsF9MYxnVrcgaN3BgcL+97/PEWa9BFaHSk2qRT+ObchTsetU
rI8UV8Hte4EHdWri3sDEHJaT3RNA4Vfbolro
-----END CERTIFICATE-----
"""
TEST_KEY = """-----BEGIN PRIVATE KEY-----
MIIEvwIBADANBgkqhkiG9w0BAQEFAASCBKkwggSlAgEAAoIBAQC1lDOVcsekdBqL
GvC+SoFAj+X6Z11NTBM6sbDCLoWdiWhk6k1SNq988aMGQ2knSSvCQjPd/WFqRkXq
YeFj3P6LwrhWa41qRpTzak3dAzTUEP+XX5J+T3KRI1nQuAhAi/Xkny11Z5MhZevw
09O8/HudK2wVnF73hp7F95yXuu9SsuNSMwnES/o6QZehdLxLTQlon1Dk7p0QWF/H
XAFIuEmE9JhFoBmrB2uVlI8HpAn9PXmnpTryWEY5d8oTqbVyaKAD51Md+Vz6TIj2
tV6SQZ1B0gUjtZfgr4vqTnDbzq4Zwttss/FuUhfR5wSjAudZDqDfTwFk5/hEFqi+
RJoFHzd1AgMBAAECggEAVhP3kDVlZxSTMLaIwezX8R9GSrqNhIM36m8p+CPNu6zU
DGL2XK8H6hcyzVlPlAwf7msr42SmtZaytjXIf2rYULDyaiV6WJM1MV+HoepPNOkK
AVyROce37A3yGfvkDZVL8CF1j16WZRLIEtaYXdLjVtKq3mPOsVDkG70SQuufYHgY
vDgVfozScckwHM7xt4H+6c47zGG7fX9NCzI9Tjaq6/10d2Tcpo8HY2hTYLrynwkp
1qOBOUYJYCd6TCzSiDfWkEfXxBbVfgq+RnDVkoqCv+1xEji+eOw73pt9X0E4nUuv
BuJTja43bOYe4qNejDwmzWBf2Vsgthvw6AAu9ysTUQKBgQDe2RhKAyBFY38uDvWI
W30vL1nK+2K5FN2tm41d1Sv9605fqp6Xf6d7fMAyEYJyD1adoCdKzaBLo1SWjL58
6hl2l6UZdjxqnvAapTeC6VpXQyB5VFDdJk6P4NJP/canpPGEyvgRxHnc3a3LvP4i
9QfSg/kNtR1Bi2OnMsuLDJW+QwKBgQDQl2vAIN4LZznX+L8XZ/x+RF6gGApTdZKr
fh01/NOUDqdv1uIY5mzXlnE6xfUixfTC6lgiVcTpCKIkkOm3H4KOcbXQvoZii5zM
kvUbaNQc8I1ZDfgvwU+kHAN+v2PivW0SUUzpDpayYA5G91ZEcYSW1vE/xue8BJFU
Pei8PydD5wKBgQCFGXc3ZWyV5RpmAQtHeRVo5EgmQ0UwtDS+50RlAdh3nV4/J2H3
rIf06orEnM6jn2OlW618MRqHcrMoBEIVy6CPw30ZmxP0vp872ugv6X5K1k4ECYcO
vz13E9mpazKGmK6kGLJXsljywPh30pabfGxCoQ5U0JL7vew0RdNqZobdjwKBgQCh
psdtVMtfoPbV5cMJu5+Upx2CCj9uYG5zEsBGh5HcauLdrHT6AREWnlNPzfvkn+7I
Y1479aYtRnCJz/gf336JL5xMkmqI0lOIwtbLEBlZ+B5Chq3xLGmw77jRsDcTj+OI
T5NABftJb2GBI8sqLaMoVpkN6PLL5epOk8/am0KtvwKBgQCLz+wSP66aaltgxPDt
SybDeDcS1SU2IoLG13wEP3pcTz+d7C9H5DDug4BI1Y9Edj3moZExQL5hPl0WyASQ
tpKMd4vRzMnBdPkcdYjTj6WuorCTzUvfaDcT6SHMk/1ZrFemlFbtuulCuYI8uWkl
xdQbdrsaH8BieroLjSC5JN6U2A==
-----END PRIVATE KEY-----
"""

UNRELATED_ROOT = """-----BEGIN CERTIFICATE-----
MIIDRTCCAi2gAwIBAgIUf4kp8SMJDqbl7yyPiWGE8coF4HwwDQYJKoZIhvcNAQEL
BQAwKTEnMCUGA1UEAwweVW5yZWxhdGVkIFN5bnRoZXRpYyBUcnVzdCBSb290MCAX
DTI2MTAyNzEwMjAyMVoYDzIxMjYxMDAzMTAyMDIxWjApMScwJQYDVQQDDB5VbnJl
bGF0ZWQgU3ludGhldGljIFRydXN0IFJvb3QwggEiMA0GCSqGSIb3DQEBAQUAA4IB
DwAwggEKAoIBAQCecZ+NOjvZV6ASPvYygO3JTS1BGtSnIDWpmaF46jPkne5GeREd
vEj3/zStVFwdPHF6nF3G8ANuY1pk/R9m+U2xPZiUp/dCohgfXDQ/at4+Hp8ZFKny
Jmx4qylpAw62KbzMyw0UyfOp4hWyj657uu5+yGzdQwFDDHtU5hrIzSvcOvXpD0la
fNJ/Q19SkT+stNuw/Q/3PbSABYH0+wjiElOYUKoF0pKnqokkplPxbMuPgOgECMFC
/Z976o5o71M9GaaeTUawz1tVqb15V1FB21rprTbTJJE/54PNsdWVSUW0PCPrvslc
8aqbhdMbHglLRPGwm+jaNCimL4+4ia3X9Q0lAgMBAAGjYzBhMB0GA1UdDgQWBBTY
lFkWFS6X07DLKdh+f6oxaulWsjAfBgNVHSMEGDAWgBTYlFkWFS6X07DLKdh+f6ox
aulWsjAOBgNVHQ8BAf8EBAMCAQYwDwYDVR0TAQH/BAUwAwEB/zANBgkqhkiG9w0B
AQsFAAOCAQEAOOXfbtG4D4Xk4OhQdM5vah35FBwoDJa+Ukb8xWJVtbFqJ6A89K73
ZXtTQC/Kk1J79gbbMqTH0RnOYj6d88RXAJ3WoBFNg6my0MtPYEcQyFYqfRtHn8aC
4/hT94PMAXsP0QtwPFrr83+kyJx06O4uP3aNC4mweuc0tWDl54DKIBzOyr2Zgjef
Y+DY1k1Jvgvv89MQcFNVsfgyWZLeKBKJYyXvwgpMggDH0yY6v+I/6kyrfLO4viFl
lFNhBemzKOACZ+Q0S3VjsrbakSXDdZ27VsvFRQ7jB2Lscn91XWRtqxsWsBWiVjWC
8/aHoUHYsp9+xhVqz5tnddajhHJ88Mu8pQ==
-----END CERTIFICATE-----
"""


class SystemTrustTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.certificate = Path(self.temporary.name) / 'certificate.pem'
        self.key = Path(self.temporary.name) / 'key.pem'
        self.certificate.write_text(TEST_CERT)
        self.key.write_text(TEST_KEY)
        self.empty_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        defaults = ssl.get_default_verify_paths()
        self.no_default_paths = defaults._replace(cafile=None, capath=None)
        self.environment = {key: value for key, value in os.environ.items()
                            if key not in {'SSL_CERT_FILE', 'SSL_CERT_DIR'}}

    def context(self, environment=None, defaults=None, system_bundle=None):
        # Mock discovery only; CA loading and TLS verification remain real.
        with patch.dict(os.environ, self.environment if environment is None else environment, clear=True), \
             patch('aclad.web_fetch.ssl.create_default_context', return_value=self.empty_context), \
             patch('aclad.web_fetch.ssl.get_default_verify_paths', return_value=defaults or self.no_default_paths), \
             patch('aclad.web_fetch._SYSTEM_CA_BUNDLE', str(system_bundle or self.certificate)):
            return web_fetch._tls_context()

    def handshake(self, context, hostname='research.example'):
        server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        server_context.load_cert_chain(self.certificate, self.key)
        client_in, client_out = ssl.MemoryBIO(), ssl.MemoryBIO()
        server_in, server_out = ssl.MemoryBIO(), ssl.MemoryBIO()
        client = context.wrap_bio(client_in, client_out, server_side=False, server_hostname=hostname)
        server = server_context.wrap_bio(server_in, server_out, server_side=True)
        complete = set()
        for _ in range(20):
            for label, endpoint in (('client', client), ('server', server)):
                if label in complete:
                    continue
                try:
                    endpoint.do_handshake()
                    complete.add(label)
                except ssl.SSLWantReadError:
                    pass
            if client_out.pending:
                server_in.write(client_out.read())
            if server_out.pending:
                client_in.write(server_out.read())
            if len(complete) == 2:
                return client.version()
        self.fail('TLS handshake did not finish.')

    def test_missing_python_defaults_loads_existing_system_bundle(self):
        context = self.context()
        self.assertGreater(context.cert_store_stats()['x509_ca'], 0)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)
        self.assertIsNotNone(self.handshake(context))

    def test_explicit_ca_environment_never_uses_fallback(self):
        for key, value in [('SSL_CERT_FILE', '/missing.pem'), ('SSL_CERT_DIR', '/missing'),
                            ('SSL_CERT_FILE', ''), ('SSL_CERT_DIR', '')]:
            with self.subTest(key=key, value=value):
                environment = dict(self.environment, **{key: value})
                context = self.context(environment=environment)
                with self.assertRaises(ssl.SSLCertVerificationError):
                    self.handshake(context)

    def test_missing_system_bundle_still_rejects_untrusted_certificate(self):
        context = self.context(system_bundle=Path(self.temporary.name) / 'missing.pem')
        with self.assertRaises(ssl.SSLCertVerificationError):
            self.handshake(context)

    def test_fallback_does_not_disable_hostname_verification(self):
        context = self.context()
        with self.assertRaises(ssl.SSLCertVerificationError):
            self.handshake(context, 'different.example')

    def test_existing_default_trust_is_preserved(self):
        self.empty_context.load_verify_locations(cadata=TEST_CERT)
        initial = self.empty_context.get_ca_certs(binary_form=True)
        context = self.context(system_bundle=Path(self.temporary.name) / 'missing.pem')
        self.assertIs(context, self.empty_context)
        self.assertEqual(context.get_ca_certs(binary_form=True), initial)
        self.assertIsNotNone(self.handshake(context))

    def test_available_default_ca_directory_is_not_replaced(self):
        context = self.context(defaults=self.no_default_paths._replace(capath='/system/certificates'))
        with self.assertRaises(ssl.SSLCertVerificationError):
            self.handshake(context)

    def test_available_default_ca_file_is_not_replaced(self):
        context = self.context(defaults=self.no_default_paths._replace(cafile='/system/certificates.pem'))
        with self.assertRaises(ssl.SSLCertVerificationError):
            self.handshake(context)

    def test_corrupt_system_bundle_fails_closed(self):
        invalid_bundle = Path(self.temporary.name) / 'corrupt.pem'
        invalid_bundle.write_text('This is not a certificate.')
        with self.assertRaises(ssl.SSLError):
            self.context(system_bundle=invalid_bundle)

    def test_loaded_system_trust_still_rejects_untrusted_peer(self):
        unrelated_bundle = Path(self.temporary.name) / 'unrelated-root.pem'
        unrelated_bundle.write_text(UNRELATED_ROOT)
        context = self.context(system_bundle=unrelated_bundle)
        self.assertGreater(context.cert_store_stats()['x509_ca'], 0)
        with self.assertRaises(ssl.SSLCertVerificationError):
            self.handshake(context)

import logging
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings
from .proxy import LoopbackProxyMiddleware, PrivateFormatter


class ProductionBoundaryTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.middleware = LoopbackProxyMiddleware(lambda request: HttpResponse(request.META['REMOTE_ADDR']))

    def test_only_loopback_proxy_can_supply_client_identity(self):
        for peer in ['203.0.113.5', '', '127.0.0.2']:
            response = self.middleware(self.factory.get('/', REMOTE_ADDR=peer,
                HTTP_X_REAL_IP='192.0.2.1', HTTP_X_FORWARDED_PROTO='https'))
            self.assertEqual(response.status_code, 400)

    def test_missing_malformed_or_multiple_addresses_rejected(self):
        for address in ['', 'not-an-ip', '192.0.2.1, 192.0.2.2']:
            self.assertEqual(self.middleware(self.factory.get('/', REMOTE_ADDR='127.0.0.1',
                HTTP_X_REAL_IP=address, HTTP_X_FORWARDED_PROTO='https')).status_code, 400)
        self.assertEqual(self.middleware(self.factory.get('/', REMOTE_ADDR='127.0.0.1',
            HTTP_X_REAL_IP='192.0.2.1', HTTP_X_FORWARDED_PROTO='https,http')).status_code, 400)

    @override_settings(SECURE_PROXY_SSL_HEADER=('HTTP_X_FORWARDED_PROTO', 'https'))
    def test_verified_address_and_https_scheme(self):
        request = self.factory.get('/', REMOTE_ADDR='127.0.0.1', HTTP_X_REAL_IP='2001:db8::1',
            HTTP_X_FORWARDED_FOR='spoofed', HTTP_X_FORWARDED_PROTO='https')
        self.assertEqual(self.middleware(request).content, b'2001:db8::1')
        self.assertTrue(request.is_secure())

    def test_private_log_formatter_omits_sensitive_context_and_exception(self):
        record = logging.LogRecord('django.request', logging.ERROR, 'file', 1,
                                   'secret request password', (), (ValueError, ValueError('private-data'), None))
        record.status_code = 500
        self.assertEqual(PrivateFormatter().format(record), 'ERROR django.request status=500')

import ipaddress
import logging
from django.http import HttpResponseBadRequest


class LoopbackProxyMiddleware:
    """Trust exactly one local proxy; it must replace both forwarding headers."""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.META.get("REMOTE_ADDR") not in {"127.0.0.1", "::1"}:
            return HttpResponseBadRequest("Invalid proxy connection.")
        try:
            address = str(ipaddress.ip_address(request.META.get("HTTP_X_REAL_IP", "")))
        except ValueError:
            return HttpResponseBadRequest("Invalid proxy address.")
        if request.META.get("HTTP_X_FORWARDED_PROTO") not in {"https", "http"}:
            return HttpResponseBadRequest("Invalid proxy scheme.")
        # Login throttles hash this verified address; ignore X-Forwarded-For entirely.
        request.META["REMOTE_ADDR"] = address
        return self.get_response(request)


class PrivateFormatter(logging.Formatter):
    def format(self, record):
        return f"{record.levelname} {record.name} status={getattr(record, 'status_code', '-')}"

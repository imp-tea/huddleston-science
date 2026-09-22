from django.shortcuts import redirect
from django.urls import reverse
from django.utils.cache import add_never_cache_headers


class AccountMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated and request.user.must_change_password and request.path not in {
            reverse("password_change"), reverse("logout"),
        }:
            response = redirect("password_change")
        else:
            response = self.get_response(request)
        # Back navigation on shared classroom computers must not expose saved pages.
        add_never_cache_headers(response)
        return response

"""
Per-host middleware for Day Loop.

Runs after django_hosts.middleware.HostsRequestMiddleware, so
request.host is already set.

- HostCookieNamesMiddleware: picks the session cookie name for the current
  host (dl_<host>_sid). CSRF uses CSRF_USE_SESSIONS, so its secret lives in
  this per-host session.
- PerHostSessionMiddleware: session middleware that reads and writes the
  per-host session cookie. Cookies are host-only (SESSION_COOKIE_DOMAIN is
  not set), so a login on one host never reaches another.
- ApexRedirectMiddleware: redirects the bare domain (PARENT_HOST) to www.
"""
from importlib import import_module

from django.conf import settings
from django.http import HttpResponsePermanentRedirect
from django.utils.cache import patch_vary_headers


def _host_name(request):
    host = getattr(request, 'host', None)
    return host.name if host is not None else settings.DEFAULT_HOST


class HostCookieNamesMiddleware:
    """Set request.session_cookie_name for the current host."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        name = _host_name(request)
        request.session_cookie_name = f'dl_{name}_sid'
        return self.get_response(request)


class PerHostSessionMiddleware:
    """Session middleware with a cookie name chosen per host."""

    def __init__(self, get_response):
        self.get_response = get_response
        self.engine = import_module(settings.SESSION_ENGINE)

    def __call__(self, request):
        cookie_name = request.session_cookie_name
        session_key = request.COOKIES.get(cookie_name)
        request.session = self.engine.SessionStore(session_key)

        response = self.get_response(request)

        accessed = request.session.accessed
        modified = request.session.modified
        empty = request.session.is_empty()

        if accessed:
            patch_vary_headers(response, ('Cookie',))
        if (modified or settings.SESSION_SAVE_EVERY_REQUEST) and not empty:
            if request.session.get_expire_at_browser_close():
                max_age = None
            else:
                max_age = request.session.get_expiry_age()
            request.session.save()
            response.set_cookie(
                cookie_name,
                request.session.session_key,
                max_age=max_age,
                # SESSION_COOKIE_DOMAIN is deliberately not used: host-only cookies.
                path=settings.SESSION_COOKIE_PATH,
                secure=settings.SESSION_COOKIE_SECURE or None,
                httponly=settings.SESSION_COOKIE_HTTPONLY or None,
                samesite=settings.SESSION_COOKIE_SAMESITE,
            )
        return response


class ApexRedirectMiddleware:
    """
    Redirect the bare domain (settings.PARENT_HOST, e.g. dayloop.example.com)
    to www.<PARENT_HOST>. In dev this sends localhost:8000 to www.localhost:8000.

    Production can also redirect at the proxy; this is the in-app fallback.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        parent = getattr(settings, 'PARENT_HOST', '').lstrip('.')
        if parent and request.get_host().lower() == parent.lower():
            scheme = 'https' if request.is_secure() else 'http'
            return HttpResponsePermanentRedirect(
                f'{scheme}://www.{parent}{request.get_full_path()}'
            )
        return self.get_response(request)

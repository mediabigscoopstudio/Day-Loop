"""
Host-based routing for Day Loop.

One Django project serves three surfaces, selected by the request host:

    www.*     -> customer storefront   (dayloop.urls_www)
    seller.*  -> seller portal         (dayloop.urls_seller)
    admin.*   -> internal admin panel  (dayloop.urls_admin)

Bare `localhost` falls back to the storefront.

Each surface also gets its own session cookie so logging in on one host
does not log you in on another.
"""
from importlib import import_module

from django.conf import settings
from django.utils.cache import patch_vary_headers

HOST_CONFIG = {
    'www': {
        'urlconf': 'dayloop.urls_www',
        'session_cookie': 'dayloop_www_sessionid',
    },
    'seller': {
        'urlconf': 'dayloop.urls_seller',
        'session_cookie': 'dayloop_seller_sessionid',
    },
    'admin': {
        'urlconf': 'dayloop.urls_admin',
        'session_cookie': 'dayloop_admin_sessionid',
    },
}
DEFAULT_SURFACE = 'www'


def surface_for_host(host):
    """Return 'www' | 'seller' | 'admin' for a host header value."""
    hostname = host.split(':', 1)[0].lower()
    first_label = hostname.split('.', 1)[0]
    if first_label in HOST_CONFIG and hostname != first_label:
        return first_label
    return DEFAULT_SURFACE


class HostRoutingMiddleware:
    """Pick the URLconf and session cookie for the current host."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        surface = surface_for_host(request.get_host())
        config = HOST_CONFIG[surface]
        request.surface = surface
        request.urlconf = config['urlconf']
        request.session_cookie_name = config['session_cookie']
        return self.get_response(request)


class PerHostSessionMiddleware:
    """
    Session middleware that uses a cookie name chosen per host.

    Must be placed after HostRoutingMiddleware. Replaces Django's
    SessionMiddleware, which only supports one global cookie name.
    """

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
                domain=settings.SESSION_COOKIE_DOMAIN,
                path=settings.SESSION_COOKIE_PATH,
                secure=settings.SESSION_COOKIE_SECURE or None,
                httponly=settings.SESSION_COOKIE_HTTPONLY or None,
                samesite=settings.SESSION_COOKIE_SAMESITE,
            )
        return response

"""
Access control for the dash host.

Layer 2 (this module): SuperuserRequiredMixin on every dash view, including
modals, partials and JSON endpoints. HTMX and JSON requests get a 403; normal
page loads are redirected to /login/.
Layer 1 is dash.middleware.DashAccessMiddleware; layer 3 is the login view.
"""
from urllib.parse import quote

from django.contrib.auth.mixins import AccessMixin
from django.core.cache import cache
from django.http import HttpResponseForbidden, HttpResponseRedirect

LOGIN_URL = '/login/'
MAX_ATTEMPTS = 5
WINDOW_SECONDS = 15 * 60


def is_dash_admin(user):
    """Only active superusers. Staff, sellers and customers are not admitted."""
    return bool(user and user.is_authenticated and user.is_active and user.is_superuser)


def wants_machine_response(request):
    """HTMX partials and JSON endpoints must not receive a login redirect."""
    return (
        request.headers.get('HX-Request') == 'true'
        or 'application/json' in request.headers.get('Accept', '')
        or request.path.startswith('/api/')
    )


def deny(request):
    if wants_machine_response(request):
        return HttpResponseForbidden('Forbidden')
    target = LOGIN_URL
    if request.method == 'GET' and request.path != LOGIN_URL:
        target = f'{LOGIN_URL}?next={quote(request.get_full_path())}'
    return HttpResponseRedirect(target)


class SuperuserRequiredMixin(AccessMixin):
    def dispatch(self, request, *args, **kwargs):
        if not is_dash_admin(request.user):
            return deny(request)
        return super().dispatch(request, *args, **kwargs)


# ---- failed-login throttle (cache based, per IP + username) ----

def _key(ip, username):
    return f'dash-login-fail:{ip}:{(username or "").strip().lower()}'


def client_ip(request):
    return request.META.get('REMOTE_ADDR', 'unknown')


def is_throttled(request, username):
    return cache.get(_key(client_ip(request), username), 0) >= MAX_ATTEMPTS


def record_failure(request, username):
    key = _key(client_ip(request), username)
    try:
        cache.add(key, 0, WINDOW_SECONDS)
        cache.incr(key)
    except ValueError:
        cache.set(key, 1, WINDOW_SECONDS)


def clear_failures(request, username):
    cache.delete(_key(client_ip(request), username))

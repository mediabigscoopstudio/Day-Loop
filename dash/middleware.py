"""Layer 1: host-scoped middleware. Only affects the dash host."""
from django.contrib.auth import logout

from .access import LOGIN_URL, deny, is_dash_admin

# Reachable without a session. Everything else on dash needs a superuser.
PUBLIC_PATHS = (LOGIN_URL,)
PUBLIC_PREFIXES = ('/static/',)


class DashAccessMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        host = getattr(request, 'host', None)
        if host is None or host.name != 'dash':
            return self.get_response(request)

        path = request.path
        if path in PUBLIC_PATHS or path.startswith(PUBLIC_PREFIXES):
            return self.get_response(request)

        user = request.user
        if is_dash_admin(user):
            return self.get_response(request)

        if user.is_authenticated:
            # Logged in but not a superuser (or deactivated): end the session.
            logout(request)
        return deny(request)

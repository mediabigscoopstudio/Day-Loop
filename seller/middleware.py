"""Layer 1: host-scoped middleware. Only affects the seller host."""
from django.contrib.auth import logout

from .access import LOGIN_URL, deny, get_seller

PUBLIC_PATHS = (LOGIN_URL, '/register/')
PUBLIC_PREFIXES = ('/static/', '/media/')


class SellerAccessMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        host = getattr(request, 'host', None)
        if host is None or host.name != 'seller':
            return self.get_response(request)
        path = request.path
        if path in PUBLIC_PATHS or path.startswith(PUBLIC_PREFIXES):
            return self.get_response(request)
        if get_seller(request.user) is not None:
            return self.get_response(request)
        if request.user.is_authenticated:
            logout(request)           # a customer or staff session is not welcome here
        return deny(request)

"""
Seller-host access control.

A "seller" is an active account that has a SellerProfile and is neither staff nor a superuser
(admins use the dash host). Customers and staff are denied with one generic error.
Layer 1 is seller.middleware.SellerAccessMiddleware (host-scoped); layer 2 is the mixins here.
Everything a view loads is scoped to request.seller, so another seller's ids are 404s.
"""
from urllib.parse import quote

from django.http import HttpResponseForbidden, HttpResponseRedirect

from sellers.models import SellerProfile

LOGIN_URL = '/login/'


def get_seller(user):
    """The user's SellerProfile if they qualify as a seller, else None."""
    if not (user and user.is_authenticated and user.is_active) or user.is_staff or user.is_superuser:
        return None
    try:
        return user.seller_profile
    except SellerProfile.DoesNotExist:
        return None


def wants_machine_response(request):
    return (request.headers.get('HX-Request') == 'true'
            or 'application/json' in request.headers.get('Accept', '')
            or request.path.startswith('/api/'))


def deny(request):
    if wants_machine_response(request):
        return HttpResponseForbidden('Forbidden')
    target = LOGIN_URL
    if request.method == 'GET' and request.path != LOGIN_URL:
        target = f'{LOGIN_URL}?next={quote(request.get_full_path())}'
    return HttpResponseRedirect(target)


class SellerRequiredMixin:
    """Any seller (even one still onboarding). Sets self.seller."""

    def dispatch(self, request, *args, **kwargs):
        seller = get_seller(request.user)
        if seller is None:
            return deny(request)
        request.seller = self.seller = seller
        return super().dispatch(request, *args, **kwargs)


class ApprovedSellerMixin(SellerRequiredMixin):
    """Only approved sellers: products, inventory, orders and payouts."""

    def dispatch(self, request, *args, **kwargs):
        seller = get_seller(request.user)
        if seller is None:
            return deny(request)
        if not seller.is_approved:
            if wants_machine_response(request):
                return HttpResponseForbidden('Your seller account is not approved yet.')
            return HttpResponseRedirect('/status/')
        request.seller = self.seller = seller
        return super(SellerRequiredMixin, self).dispatch(request, *args, **kwargs)

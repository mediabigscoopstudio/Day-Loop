"""Seller navigation and base views. Reuses the ui app's shell, modals and toasts."""
from django.views.generic import TemplateView

from .access import ApprovedSellerMixin, SellerRequiredMixin

NAV = [
    {'key': 'home', 'label': 'Overview', 'url': '/', 'icon': 'home'},
    {'key': 'products', 'label': 'Products', 'url': '/products/', 'icon': 'layers'},
    {'key': 'inventory', 'label': 'Inventory', 'url': '/inventory/', 'icon': 'box'},
    {'key': 'orders', 'label': 'Orders', 'url': '/orders/', 'icon': 'cart'},
    {'key': 'earnings', 'label': 'Earnings', 'url': '/earnings/', 'icon': 'rupee'},
    {'key': 'account', 'label': 'Account', 'url': '/account/', 'icon': 'user'},
]
BOTTOM_NAV = [
    {'key': 'home', 'label': 'Home', 'url': '/', 'icon': 'home'},
    {'key': 'products', 'label': 'Products', 'url': '/products/', 'icon': 'layers'},
    {'key': 'inventory', 'label': 'Inventory', 'url': '/inventory/', 'icon': 'box'},
    {'key': 'orders', 'label': 'Orders', 'url': '/orders/', 'icon': 'cart'},
    {'key': 'account', 'label': 'Account', 'url': '/account/', 'icon': 'user'},
]
# Sellers still being reviewed only get these.
LIMITED_NAV = [n for n in NAV if n['key'] in ('home', 'account')]


def shell_context(seller, active):
    approved = seller.is_approved
    return {
        'nav': NAV if approved else [{'key': 'home', 'label': 'Status', 'url': '/status/', 'icon': 'info'}] + LIMITED_NAV[1:],
        'bottom_nav': BOTTOM_NAV if approved else None,
        'fab': {'url': '/products/new/', 'label': 'Add product'} if approved else None,
        'active': active, 'home_url': '/', 'seller': seller,
    }


class SellerPageView(SellerRequiredMixin, TemplateView):
    """Page any seller may open (status, account, onboarding)."""
    active = ''

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update(shell_context(self.seller, self.active))
        return ctx


class ApprovedPageView(ApprovedSellerMixin, TemplateView):
    """Page only approved sellers may open."""
    active = ''

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update(shell_context(self.seller, self.active))
        return ctx

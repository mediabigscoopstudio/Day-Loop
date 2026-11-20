"""Shared pieces for dash views: navigation and the base view class."""
from django.views.generic import TemplateView

from .access import SuperuserRequiredMixin

NAV = [
    {'key': 'overview', 'label': 'Overview', 'url': '/', 'icon': 'home'},
    {'key': 'orders', 'label': 'Orders', 'url': '/orders/', 'icon': 'box'},
    {'key': 'sellers', 'label': 'Sellers', 'url': '/sellers/', 'icon': 'users'},
    {'key': 'products', 'label': 'Products', 'url': '/products/', 'icon': 'layers'},
    {'key': 'customers', 'label': 'Customers', 'url': '/customers/', 'icon': 'user'},
    {'key': 'analytics', 'label': 'Analytics', 'url': '/analytics/', 'icon': 'chart'},
]


def shell_context(active):
    from sellers.models import SellerProfile
    return {
        'nav': NAV, 'active': active, 'home_url': '/',
        'search_url': '/search/', 'bell_url': '/notifications/',
        'bell_count': SellerProfile.objects.filter(status=SellerProfile.Status.PENDING).count(),
    }


class DashPageView(SuperuserRequiredMixin, TemplateView):
    """Full-page dash view rendered inside the shell."""
    active = ''

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update(shell_context(self.active))
        return ctx

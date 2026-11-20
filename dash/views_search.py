from django.contrib.auth import get_user_model
from django.db.models import Exists, OuterRef, Q
from django.shortcuts import render
from django.views import View

from catalog.models import Product, ProductVariant
from orders.models import Order
from sellers.models import SellerProfile

from .access import SuperuserRequiredMixin
from .services import metrics

LIMIT = 4
User = get_user_model()


class SearchView(SuperuserRequiredMixin, View):
    """Debounced global search: a few results per kind, grouped."""

    def get(self, request):
        q = request.GET.get('q', '').strip()[:80]
        groups = []
        if len(q) >= 2:
            orders = list(Order.objects.select_related('customer').filter(
                Q(number__icontains=q) | Q(customer__username__icontains=q) | Q(customer__email__icontains=q)
            ).order_by('-placed_at')[:LIMIT])
            sellers = list(SellerProfile.objects.filter(
                Q(business_name__icontains=q) | Q(user__email__icontains=q) | Q(gst_number__icontains=q)
            ).order_by('business_name')[:LIMIT])
            products = list(Product.objects.select_related('seller').filter(
                Q(name__icontains=q) | Q(brand__icontains=q)
                | Exists(ProductVariant.objects.filter(product=OuterRef('pk'), sku__icontains=q))
            ).order_by('name')[:LIMIT])
            customers = list(User.objects.filter(
                Q(username__icontains=q) | Q(email__icontains=q) | Q(first_name__icontains=q) | Q(last_name__icontains=q),
                orders__isnull=False).distinct().order_by('username')[:LIMIT])
            groups = [g for g in (('Orders', 'orders', orders), ('Sellers', 'sellers', sellers),
                                  ('Products', 'products', products), ('Customers', 'customers', customers)) if g[2]]
        return render(request, 'dash/partials/search_results.html', {'groups': groups, 'q': q, 'too_short': len(q) < 2})


class NotificationsView(SuperuserRequiredMixin, View):
    def get(self, request):
        return render(request, 'dash/partials/notifications.html', {
            'pending_total': metrics.pending_total(), 'pending': metrics.pending_sellers(limit=5)})

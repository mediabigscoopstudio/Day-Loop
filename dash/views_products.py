from django.db.models import Count
from django.shortcuts import get_object_or_404, render
from django.views import View

from catalog.models import Category, Product
from orders.models import OrderItem
from sellers.models import SellerProfile

from .access import SuperuserRequiredMixin
from .base import DashPageView
from .htmx import trigger_response
from .listing import apply_sort, clean_params, paginate
from .services.product_filters import FILTER_KEYS, LOW_STOCK, STOCK_LEVELS, base_queryset, filter_products

SORTS = {'name': 'name', 'seller': 'seller__business_name', 'price': 'min_price', 'stock': 'total_stock',
         'created': 'created_at', 'status': 'status'}


class ProductListView(DashPageView):
    active = 'products'
    template_name = 'dash/products.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        p = clean_params(self.request.GET, FILTER_KEYS)
        qs = filter_products(base_queryset(), p)
        qs, sort, desc = apply_sort(qs, self.request.GET, SORTS, ['-created_at'])
        cat = p.get('category', '')
        subs = Category.objects.filter(parent_id=int(cat), is_active=True) if cat.isdigit() else Category.objects.none()
        ctx.update(
            page=paginate(qs, self.request.GET), f=p, low_stock=LOW_STOCK, stock_levels=STOCK_LEVELS,
            statuses=Product.Status.choices,
            sellers=SellerProfile.objects.order_by('business_name').only('id', 'business_name'),
            categories=Category.objects.filter(parent__isnull=True, is_active=True),
            subs=subs, selected_category=cat, selected_sub=p.get('subcategory', ''),
            brands=Product.objects.exclude(brand='').order_by('brand').values_list('brand', flat=True).distinct(),
            has_filters=bool(p),
        )
        return ctx


def _product(pk):
    return get_object_or_404(base_queryset(), pk=pk)


class ProductDetailModal(SuperuserRequiredMixin, View):
    def get(self, request, pk):
        product = _product(pk)
        sold = OrderItem.objects.filter(product=product).exclude(order__status='cancelled').aggregate(
            units=Count('id'))
        return render(request, 'dash/products/detail_modal.html', {
            'product': product, 'sold': sold['units'], 'low_stock': LOW_STOCK, 'modal_size': 'lg',
            'variants': product.variants.all()})


class ProductToggleView(SuperuserRequiredMixin, View):
    def get(self, request, pk):
        p = _product(pk)
        if p.status not in (Product.Status.LIVE, Product.Status.INACTIVE):
            return render(request, 'dash/products/not_toggleable.html', {'product': p, 'modal_size': 'sm'})
        off = p.is_live
        return render(request, 'ui/confirm_modal.html', {
            'modal_size': 'sm', 'variant': 'warning' if off else 'neutral', 'icon': 'alert' if off else 'check',
            'title': f'{"Deactivate" if off else "Activate"} product',
            'message': f'{"Deactivate" if off else "Activate"} “{p.name}”?',
            'consequence': ('Customers will no longer be able to see or buy this product.' if off
                            else 'The product will be visible and purchasable on the storefront again.'),
            'confirm_label': 'Deactivate' if off else 'Activate', 'post_url': f'/products/{p.pk}/toggle/',
        })

    def post(self, request, pk):
        p = _product(pk)
        if p.status not in (Product.Status.LIVE, Product.Status.INACTIVE):
            return render(request, 'dash/products/not_toggleable.html', {'product': p, 'modal_size': 'sm'}, status=422)
        p.status = Product.Status.INACTIVE if p.is_live else Product.Status.LIVE
        p.save(update_fields=['status', 'updated_at'])
        return trigger_response(f'“{p.name}” {"activated" if p.is_live else "deactivated"}.', events=('products-changed',))


def _selected_ids(request):
    raw = request.POST.getlist('ids') if request.method == 'POST' else request.GET.getlist('ids')
    return sorted({int(v) for v in raw if v.isdigit()})[:500]


class ProductBulkView(SuperuserRequiredMixin, View):
    """GET -> confirm popup for the ticked rows; POST -> apply."""

    def _action(self, request):
        a = request.POST.get('action') or request.GET.get('action')
        return a if a in ('activate', 'deactivate') else None

    def get(self, request):
        action, ids = self._action(request), _selected_ids(request)
        if not action or not ids:
            return render(request, 'dash/products/bulk_empty.html', {'modal_size': 'sm'})
        n = Product.objects.filter(pk__in=ids).count()
        off = action == 'deactivate'
        return render(request, 'ui/confirm_modal.html', {
            'modal_size': 'sm', 'variant': 'warning' if off else 'neutral', 'icon': 'alert' if off else 'check',
            'title': f'{action.title()} {n} product{"s" if n != 1 else ""}',
            'message': f'{action.title()} {n} selected product{"s" if n != 1 else ""}?',
            'consequence': ('They will be hidden from customers until activated again.' if off
                            else 'They will become visible and purchasable on the storefront.'),
            'confirm_label': action.title(), 'post_url': '/products/bulk/',
            'extra': {'action': action, 'ids': ','.join(map(str, ids))},
        })

    def post(self, request):
        action = self._action(request)
        raw = request.POST.get('ids', '')
        ids = sorted({int(v) for v in raw.split(',') if v.strip().isdigit()})[:500]
        if not action or not ids:
            return render(request, 'dash/products/bulk_empty.html', {'modal_size': 'sm'}, status=422)
        # Only live <-> inactive move here; drafts, pending and rejected products are untouched.
        src, dst = ((Product.Status.INACTIVE, Product.Status.LIVE) if action == 'activate'
                    else (Product.Status.LIVE, Product.Status.INACTIVE))
        changed = Product.objects.filter(pk__in=ids, status=src).update(status=dst)
        return trigger_response(f'{changed} product{"s" if changed != 1 else ""} {action}d.', events=('products-changed',))

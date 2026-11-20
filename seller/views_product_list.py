"""Seller product list, bulk activate/deactivate (live products only) and duplicate."""
import json

from django.db.models import Count, Q
from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.views import View

from catalog.models import Category, Product
from dash.listing import apply_sort, clean_params, paginate

from .access import ApprovedSellerMixin
from .base import ApprovedPageView
from .services import products as svc

P = Product.Status
LOW_STOCK = 10
SORTS = {'name': 'name', 'price': 'min_price', 'stock': 'total_stock', 'updated': 'updated_at', 'status': 'status'}
NOTICES = {
    'submitted': 'Product submitted for review. We’ll let you know once it’s approved.',
    'resubmitted': 'Changes saved. The product is back in review before they go live.',
    'review': 'That product is being reviewed and can’t be edited right now.',
}


class ProductListView(ApprovedPageView):
    template_name = 'seller/products/list.html'
    active = 'products'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        p = clean_params(self.request.GET, ['status', 'category', 'stock', 'q'])
        base = svc.products_for(self.seller)
        counts = Product.objects.filter(seller=self.seller).aggregate(
            all=Count('id'), **{s.value: Count('id', filter=Q(status=s)) for s in P})
        qs = base
        if p.get('status') in P.values:
            qs = qs.filter(status=p['status'])
        if p.get('category', '').isdigit():
            qs = qs.filter(subcategory__parent_id=int(p['category']))
        stock = p.get('stock')
        if stock == 'out':
            qs = qs.filter(total_stock=0)
        elif stock == 'low':
            qs = qs.filter(total_stock__gte=1, total_stock__lte=LOW_STOCK)
        elif stock == 'in':
            qs = qs.filter(total_stock__gt=LOW_STOCK)
        if p.get('q'):
            qs = qs.filter(Q(name__icontains=p['q']) | Q(brand__icontains=p['q']) | Q(variants__sku__icontains=p['q'])).distinct()
        qs, sort, desc = apply_sort(qs, self.request.GET, SORTS, ['-updated_at'])
        notice = next((NOTICES[k] for k in NOTICES if self.request.GET.get(k) == '1' or self.request.GET.get('notice') == k), '')
        ctx.update(
            page=paginate(qs, self.request.GET), f=p, counts=counts, has_filters=bool(p), notice=notice,
            tabs=[('', 'All', counts['all'])] + [(s.value, s.label, counts[s.value]) for s in P],
            categories=Category.objects.filter(parent__isnull=True, is_active=True), low_stock=LOW_STOCK,
            can_bulk=counts['live'] + counts['inactive'] > 0)
        return ctx


def _ids(raw):
    return sorted({int(x) for x in raw if str(x).isdigit()})[:300]


class BulkView(ApprovedSellerMixin, View):
    def _action(self, request):
        a = request.POST.get('action') or request.GET.get('action')
        return a if a in ('activate', 'deactivate') else None

    def get(self, request):
        action, ids = self._action(request), _ids(request.GET.getlist('ids'))
        n = Product.objects.filter(seller=self.seller, pk__in=ids, status=(P.INACTIVE if action == 'activate' else P.LIVE)).count() if action else 0
        if not action or not n:
            return render(request, 'seller/products/bulk_empty.html', {'modal_size': 'sm'})
        off = action == 'deactivate'
        return render(request, 'ui/confirm_modal.html', {
            'modal_size': 'sm', 'variant': 'warning' if off else 'neutral', 'icon': 'alert' if off else 'check',
            'title': f'{action.title()} {n} product{"s" if n != 1 else ""}',
            'message': f'{action.title()} {n} selected product{"s" if n != 1 else ""}?',
            'consequence': 'Customers will no longer see them until you activate them again.' if off else 'They will be visible on the storefront again.',
            'confirm_label': action.title(), 'post_url': '/products/bulk/',
            'extra': {'action': action, 'ids': ','.join(map(str, ids))}})

    def post(self, request):
        action = self._action(request)
        ids = _ids(request.POST.get('ids', '').split(','))
        if not action or not ids:
            return render(request, 'seller/products/bulk_empty.html', {'modal_size': 'sm'}, status=422)
        changed = svc.bulk_set_active(self.seller, ids, activate=(action == 'activate'))
        msg = f'{changed} product{"s" if changed != 1 else ""} {action}d.' if changed else 'Nothing to change: only live or inactive products can be switched.'
        return HttpResponse(status=204, headers={'HX-Trigger': json.dumps({
            'closeModal': True, 'products-changed': True, 'toast': {'message': msg, 'level': 'success' if changed else 'error'}})})


class DuplicateView(ApprovedSellerMixin, View):
    def post(self, request, pk):
        try:
            copy = svc.duplicate(self.seller, pk)
        except Product.DoesNotExist:
            raise Http404
        return HttpResponse(status=204, headers={'HX-Redirect': f'/products/{copy.pk}/edit/?saved=1'})

"""Inventory: stock per variant with batch/expiry badges, update popup and history."""
from datetime import date, timedelta

from django.db.models import F, Q
from django.http import Http404
from django.shortcuts import render
from django.views import View

from catalog.models import EXPIRY_WARN_DAYS, ProductVariant
from catalog.services.stock import InsufficientStock, StockError, adjust_stock
from dash.listing import apply_sort, clean_params, paginate

from .access import ApprovedSellerMixin
from .base import ApprovedPageView
from .forms_inventory import StockUpdateForm
from .views_variants import trigger

SORTS = {'name': 'product__name', 'stock': 'stock', 'expiry': 'expires_on', 'sku': 'sku'}
FILTERS = [('', 'All'), ('low', 'Low stock'), ('out', 'Out of stock'), ('expiring', f'Expiring ≤{EXPIRY_WARN_DAYS} days'), ('expired', 'Expired')]


class InventoryView(ApprovedPageView):
    template_name = 'seller/inventory.html'
    active = 'inventory'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        p = clean_params(self.request.GET, ['filter', 'q'])
        today = date.today()
        qs = ProductVariant.objects.filter(seller=self.seller).select_related('product')
        flt = p.get('filter')
        if flt == 'low':
            qs = qs.filter(stock__gt=0, stock__lte=F('low_stock_threshold'))
        elif flt == 'out':
            qs = qs.filter(stock=0)
        elif flt == 'expiring':
            qs = qs.filter(expires_on__gte=today, expires_on__lte=today + timedelta(days=EXPIRY_WARN_DAYS))
        elif flt == 'expired':
            qs = qs.filter(expires_on__lt=today)
        if p.get('q'):
            q = p['q']
            qs = qs.filter(Q(label__icontains=q) | Q(sku__icontains=q) | Q(batch_number__icontains=q) | Q(product__name__icontains=q))
        qs, sort, desc = apply_sort(qs, self.request.GET, SORTS, ['product__name', 'sort_order'])
        mine = ProductVariant.objects.filter(seller=self.seller)
        ctx.update(
            page=paginate(qs, self.request.GET), f=p, filters=FILTERS, has_filters=bool(p), today=today,
            n_low=mine.filter(stock__gt=0, stock__lte=F('low_stock_threshold')).count(), n_out=mine.filter(stock=0).count(),
            n_expiring=mine.filter(expires_on__gte=today, expires_on__lte=today + timedelta(days=EXPIRY_WARN_DAYS)).count(),
            n_expired=mine.filter(expires_on__lt=today).count())
        return ctx


class VariantScoped(ApprovedSellerMixin, View):
    def variant(self, pk):
        try:
            return ProductVariant.objects.select_related('product').get(pk=pk, seller=self.seller)
        except ProductVariant.DoesNotExist:
            raise Http404


class StockUpdateView(VariantScoped):
    def _render(self, request, v, form, status=200):
        return render(request, 'seller/inventory/stock_modal.html', {'variant': v, 'form': form, 'modal_size': 'sm', 'sheet': True}, status=status)

    def get(self, request, pk):
        v = self.variant(pk)
        return self._render(request, v, StockUpdateForm())

    def post(self, request, pk):
        v = self.variant(pk)
        form = StockUpdateForm(request.POST)
        if not form.is_valid():
            return self._render(request, v, form, status=422)
        d = form.cleaned_data
        try:
            v = adjust_stock(v.pk, d['action'], d['quantity'], seller=self.seller, actor=request.user, reason=d['reason'])
        except InsufficientStock as e:
            form.add_error('quantity', str(e))
            return self._render(request, v, form, status=422)
        except StockError as e:
            form.add_error(None, str(e))
            return self._render(request, v, form, status=422)
        return trigger(f'Stock for “{v.label}” is now {v.stock}.', events=('inventory-changed',))


class StockHistoryView(VariantScoped):
    def get(self, request, pk):
        v = self.variant(pk)
        return render(request, 'seller/inventory/history_modal.html', {
            'variant': v, 'rows': v.movements.select_related('actor')[:40], 'modal_size': 'md', 'sheet': True})

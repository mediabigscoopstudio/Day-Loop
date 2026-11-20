"""Variant popups (bottom sheet on phones) for an approved seller's own products."""
import json

from django.db.models import ProtectedError
from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.views import View

from catalog.models import Product, ProductVariant

from .access import ApprovedSellerMixin
from .forms_products import BulkSizesForm, VariantForm
from .services import products as svc


def trigger(message=None, events=('variants-changed',), close=True, level='success'):
    payload = {e: True for e in events}
    if close:
        payload['closeModal'] = True
    if message:
        payload['toast'] = {'message': message, 'level': level}
    return HttpResponse(status=204, headers={'HX-Trigger': json.dumps(payload)})


class ProductScopedView(ApprovedSellerMixin, View):
    """Resolves the product for THIS seller only; another seller's id is a 404."""

    def product(self, pk):
        try:
            return svc.get_product(self.seller, pk)
        except Product.DoesNotExist:
            raise Http404

    def locked(self, request, product):
        return render(request, 'seller/products/locked_modal.html', {'product': product, 'modal_size': 'sm'}, status=403)


class VariantListPartial(ProductScopedView):
    def get(self, request, pk):
        p = self.product(pk)
        variants = list(p.variants.all())
        return render(request, 'seller/products/variant_list.html', {
            'product': p, 'rows': [(v, svc.variant_problems(v)) for v in variants], 'locked': p.status == Product.Status.PENDING})


class VariantFormView(ProductScopedView):
    def _render(self, request, product, form, variant=None, status=200):
        return render(request, 'seller/products/variant_modal.html', {
            'product': product, 'form': form, 'variant': variant, 'modal_size': 'lg', 'sheet': True,
            'post_url': f'/products/{product.pk}/variants/{variant.pk}/' if variant else f'/products/{product.pk}/variants/new/',
            'chargeable': variant.chargeable_kg if variant else None, 'volumetric': variant.volumetric_kg if variant else None,
        }, status=status)

    def _variant(self, product, vid):
        try:
            return svc.get_variant(self.seller, product.pk, vid)
        except ProductVariant.DoesNotExist:
            raise Http404

    def get(self, request, pk, vid=None):
        p = self.product(pk)
        if p.status == Product.Status.PENDING:
            return self.locked(request, p)
        v = self._variant(p, vid) if vid else None
        form = VariantForm(instance=v, seller=self.seller, product=p, initial={} if v else {
            'sku': svc.suggest_sku(self.seller, p, request.GET.get('label', 'STD')), 'moq': 1, 'stock': 0, 'low_stock_threshold': 10})
        return self._render(request, p, form, v)

    def post(self, request, pk, vid=None):
        p = self.product(pk)
        if p.status == Product.Status.PENDING:
            return self.locked(request, p)
        v = self._variant(p, vid) if vid else None
        form = VariantForm(request.POST, instance=v, seller=self.seller, product=p)
        if not form.is_valid():
            return self._render(request, p, form, v, status=422)
        obj = form.save(commit=False)
        obj.product, obj.seller = p, self.seller
        if not v:
            obj.sort_order = p.variants.count()
        obj.save()
        return trigger(f'Variant “{obj.label}” {"updated" if v else "added"}.')


class VariantDeleteView(ProductScopedView):
    def _get(self, p, vid):
        try:
            return svc.get_variant(self.seller, p.pk, vid)
        except ProductVariant.DoesNotExist:
            raise Http404

    def get(self, request, pk, vid):
        p = self.product(pk)
        if p.status == Product.Status.PENDING:
            return self.locked(request, p)
        v = self._get(p, vid)
        if v.order_items.exists():
            return render(request, 'seller/products/variant_blocked.html', {'variant': v, 'modal_size': 'sm'})
        return render(request, 'ui/confirm_modal.html', {
            'modal_size': 'sm', 'variant': 'danger', 'icon': 'trash', 'title': 'Delete variant',
            'message': f'Delete “{v.label}”?', 'consequence': 'Its price and stock history will be removed. This cannot be undone.',
            'confirm_label': 'Delete', 'post_url': f'/products/{p.pk}/variants/{v.pk}/delete/'})

    def post(self, request, pk, vid):
        p = self.product(pk)
        if p.status == Product.Status.PENDING:
            return self.locked(request, p)
        v = self._get(p, vid)
        try:
            label = v.label
            v.delete()
        except ProtectedError:
            return render(request, 'seller/products/variant_blocked.html', {'variant': v, 'modal_size': 'sm'}, status=422)
        return trigger(f'Variant “{label}” deleted.')


class BulkSizesView(ProductScopedView):
    def get(self, request, pk):
        p = self.product(pk)
        if p.status == Product.Status.PENDING:
            return self.locked(request, p)
        return render(request, 'seller/products/sizes_modal.html', {'product': p, 'form': BulkSizesForm(), 'modal_size': 'md', 'sheet': True})

    def post(self, request, pk):
        p = self.product(pk)
        if p.status == Product.Status.PENDING:
            return self.locked(request, p)
        form = BulkSizesForm(request.POST)
        if not form.is_valid():
            return render(request, 'seller/products/sizes_modal.html', {'product': p, 'form': form, 'modal_size': 'md', 'sheet': True}, status=422)
        existing = {v.label.lower() for v in p.variants.all()}
        made = 0
        for label in form.cleaned_data['sizes']:
            if label.lower() in existing:
                continue
            ProductVariant.objects.create(
                product=p, seller=self.seller, label=label, sku=svc.suggest_sku(self.seller, p, label), mrp=0, price=0, stock=0,
                gst_rate=p.subcategory.default_gst_rate, dispatch_days=self.seller.dispatch_days, sort_order=p.variants.count())
            made += 1
        return trigger(f'{made} variant{"s" if made != 1 else ""} added. Fill in price, stock and package details.')

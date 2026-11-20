from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views import View

from . import delivery
from .cart import add_to_cart, get_cart, remove_from_cart, set_cart_quantity
from .common import confirm, is_htmx, page_ctx, toast_trigger
from .selectors import visible_variants


def _qty(request, default=1):
    try:
        return max(int(request.POST.get('quantity', default)), 0)
    except ValueError:
        return default


class CartView(View):
    def get(self, request):
        return render(request, 'storefront/cart.html', page_ctx(request, area=delivery.session_area(request)))


class CartBadgeView(View):
    def get(self, request):
        return render(request, 'storefront/partials/cart_badge.html', {'cart': get_cart(request)})


class CartAddView(View):
    def post(self, request):
        v = visible_variants().select_related('product').filter(pk=request.POST.get('variant_id') or 0).first()
        qty = max(_qty(request), 1)
        if not v:
            return toast_trigger(HttpResponse(status=422), 'That item is not available right now.', 'error')
        in_cart = next((i['quantity'] for i in get_cart(request)['items'] if i['variant'].pk == v.pk), 0)
        if in_cart + qty > v.stock:
            return toast_trigger(HttpResponse(status=422), f'Only {v.stock} in stock for {v.label}.', 'error')
        add_to_cart(request, v.pk, qty)
        resp = toast_trigger(HttpResponse(status=204), f'Added {v.product.name} ({v.label}) to your cart.')
        import json
        resp['HX-Trigger'] = json.dumps({'toast': {'message': f'Added {v.product.name} to your cart.', 'level': 'success'}, 'cartChanged': True})
        return resp


class CartUpdateView(View):
    """Quantity change: re-renders the cart body so totals update without a reload."""
    def post(self, request):
        variant_id = request.POST.get('variant_id')
        v = visible_variants().filter(pk=variant_id or 0).first()
        qty = _qty(request)
        if v and qty > v.stock:
            set_cart_quantity(request, v.pk, v.stock)       # clamp; the line shows a warning if it still cannot be met
        elif variant_id:
            set_cart_quantity(request, variant_id, qty)
        resp = render(request, 'storefront/partials/cart_content.html', page_ctx(request, area=delivery.session_area(request)))
        resp['HX-Trigger'] = '{"cartChanged": true}'
        return resp


class CartRemoveView(View):
    def get(self, request, variant_id):
        from catalog.models import ProductVariant
        v = get_object_or_404(ProductVariant.objects.select_related('product'), pk=variant_id)
        return confirm(request, title='Remove item', message=f'Remove {v.product.name} ({v.label}) from your cart?',
                       consequence='You can add it back from the product page.', confirm_label='Remove',
                       post_url=request.path, icon='trash')

    def post(self, request, variant_id):
        remove_from_cart(request, variant_id)
        resp = render(request, 'storefront/partials/cart_content.html', page_ctx(request, area=delivery.session_area(request)))
        resp['HX-Retarget'] = '#cart-body'
        resp['HX-Reswap'] = 'innerHTML'
        resp['HX-Trigger'] = '{"closeModal": true, "cartChanged": true, "toast": {"message": "Item removed from your cart.", "level": "success"}}'
        return resp

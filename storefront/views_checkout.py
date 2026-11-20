from .common import StoreLoginRequired as LoginRequiredMixin
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View

from orders.models import Order
from orders.services.checkout import CheckoutError, create_order

from . import delivery, gateway
from .cart import clear_cart, get_cart
from .common import done, is_htmx, page_ctx, popup
from .models import Address

ADDR_KEY = 'checkout_address'


def chosen_address(request):
    qs = Address.objects.filter(user=request.user)
    aid = request.session.get(ADDR_KEY)
    return qs.filter(pk=aid).first() or qs.first()


class CheckoutView(View):
    def get(self, request):
        cart = get_cart(request)
        if not cart['total_items']:
            return redirect('storefront:cart')
        addr = chosen_address(request) if request.user.is_authenticated else None
        tier = delivery.session_tier(request)
        return render(request, 'storefront/checkout.html', page_ctx(
            request, address=addr, tier=tier, methods=gateway.METHODS,
            method=request.session.get('pay_method', 'upi'), area=delivery.session_area(request)))


class AddressPickerView(LoginRequiredMixin, View):
    def get(self, request):
        return popup(request, 'storefront/modals/address_picker.html', {
            'addresses': Address.objects.filter(user=request.user), 'current': chosen_address(request)})

    def post(self, request):
        a = get_object_or_404(Address, pk=request.POST.get('address_id') or 0, user=request.user)
        request.session[ADDR_KEY] = a.pk
        return done(request, 'Delivery address updated.')


class PayView(LoginRequiredMixin, View):
    """Step 1: validate, then show the mock gateway popup."""
    def post(self, request):
        cart = get_cart(request)
        addr = chosen_address(request)
        method = request.POST.get('payment_method', 'upi')
        request.session['pay_method'] = method
        err = None
        if not cart['total_items']:
            err = 'Your cart is empty.'
        elif cart['blocked']:
            err = 'Some items need your attention. Fix them in your cart first.'
        elif not addr:
            err = 'Add a delivery address first.'
        elif method not in gateway.METHOD_LABELS:
            err = 'Choose a payment method.'
        if err:
            return popup(request, 'storefront/modals/payment_result.html', {'ok': False, 'message': err, 'blocking': True}, status=422)
        return popup(request, 'storefront/modals/payment_gateway.html', {
            'total': cart['total'], 'method': method, 'method_label': gateway.METHOD_LABELS[method]})


class PayConfirmView(LoginRequiredMixin, View):
    """Step 2: run the mock gateway, then place the order through the orders service."""
    def post(self, request):
        cart = get_cart(request)
        addr = chosen_address(request)
        method = request.POST.get('payment_method', 'upi')
        if not cart['total_items'] or not addr or cart['blocked']:
            return popup(request, 'storefront/modals/payment_result.html', {'ok': False, 'message': 'Your cart changed. Please review it and try again.', 'blocking': True}, status=422)
        result = gateway.charge(cart['total'], method, request.POST.get('simulate', 'success'))
        if not result.ok:
            return popup(request, 'storefront/modals/payment_result.html', {
                'ok': False, 'message': result.message, 'total': cart['total'], 'method': method}, status=200)
        lines = [(i['variant'].pk, i['quantity']) for i in cart['items']]
        try:
            order = create_order(
                customer=request.user, lines=lines,
                address={'name': addr.name, 'line1': ', '.join(x for x in (addr.line1, addr.area) if x),
                         'city': addr.city, 'state': addr.state, 'pincode': addr.pincode},
                payment_method=gateway.METHOD_LABELS[method],
                payment_status=Order.PaymentStatus.PENDING if method == 'cod' else Order.PaymentStatus.PAID)
        except CheckoutError as e:
            return popup(request, 'storefront/modals/payment_result.html', {'ok': False, 'message': str(e), 'blocking': True}, status=422)
        clear_cart(request)
        resp = HttpResponse(status=204)
        resp['HX-Redirect'] = reverse('storefront:order-confirmation', args=[order.number])
        return resp


class OrderConfirmationView(LoginRequiredMixin, View):
    def get(self, request, number):
        order = get_object_or_404(Order.objects.filter(customer=request.user).prefetch_related(
            'seller_orders__seller', 'seller_orders__items__product', 'seller_orders__items__variant'), number=number)
        tier = delivery.session_tier(request)
        sos = list(order.seller_orders.all())
        for so in sos:
            days = max((i.variant.dispatch_days for i in so.items.all() if i.variant), default=0)
            so.eta = delivery.eta_for(tier, days)
        return render(request, 'storefront/order_confirmation.html', page_ctx(request, order=order, shipments=sos))

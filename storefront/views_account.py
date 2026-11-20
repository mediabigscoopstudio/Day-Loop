from datetime import date, timedelta

from .common import StoreLoginRequired as LoginRequiredMixin
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views import View

from orders.models import Order, SellerOrder

from . import delivery
from .cart import add_to_cart
from .common import confirm, done, page_ctx, popup, toast_trigger
from .forms import AddressForm, FrequencyForm
from .models import Address, Subscription
from .selectors import visible_variants
from .views_auth import form_modal

STEPS = [('accepted', 'Accepted'), ('packed', 'Packed'), ('shipped', 'Shipped'), ('delivered', 'Delivered')]


def my_orders(user):
    """Always scoped to the signed-in customer."""
    return Order.objects.filter(customer=user).prefetch_related('items', 'seller_orders__seller')


def chip(order):
    if order.payment_status == 'failed':
        return 'Failed'
    return 'Delivered' if order.status == 'delivered' else ('Cancelled' if order.status == 'cancelled' else 'Processing')


class AccountHomeView(LoginRequiredMixin, View):
    def get(self, request):
        orders = list(my_orders(request.user)[:3])
        return render(request, 'storefront/account/home.html', page_ctx(
            request, tab='home', recent=orders, order_count=my_orders(request.user).count(),
            sub_count=Subscription.objects.filter(user=request.user, status='active').count()))


class OrderListView(LoginRequiredMixin, View):
    def get(self, request):
        orders = list(my_orders(request.user))
        for o in orders:
            o.chip, o.item_count = chip(o), sum(i.quantity for i in o.items.all())
        return render(request, 'storefront/account/orders.html', page_ctx(request, tab='orders', orders=orders))


class OrderDetailView(LoginRequiredMixin, View):
    def get(self, request, number):
        order = get_object_or_404(my_orders(request.user).prefetch_related(
            'seller_orders__items__product', 'seller_orders__items__variant', 'seller_orders__events'), number=number)
        tier = delivery.session_tier(request)
        sos = list(order.seller_orders.all())
        for so in sos:
            reached = {e.status for e in so.events.all()}
            idx = [k for k, _ in STEPS].index(so.status) if so.status in dict(STEPS) else -1
            so.steps = [{'label': l, 'done': i <= idx or k in reached} for i, (k, l) in enumerate(STEPS)]
            so.eta = delivery.eta_for(tier, max((i.variant.dispatch_days for i in so.items.all() if i.variant), default=0))
        order.chip = chip(order)
        return render(request, 'storefront/account/order_detail.html', page_ctx(request, tab='orders', order=order, shipments=sos))


class ReorderView(LoginRequiredMixin, View):
    def post(self, request, number):
        order = get_object_or_404(my_orders(request.user), number=number)
        n = 0
        for it in order.items.all():
            if it.variant_id and visible_variants().filter(pk=it.variant_id).exists():
                add_to_cart(request, it.variant_id, it.quantity)
                n += 1
        if not n:
            return toast_trigger(HttpResponse(status=422), 'None of these items are available right now.', 'error')
        return done(request, f'{n} item(s) added to your cart.', redirect_to='/cart/')


class InvoiceView(LoginRequiredMixin, View):
    """Printable per-seller GST invoice. Customer-facing: no margin or payout numbers."""
    def get(self, request, invoice):
        so = get_object_or_404(SellerOrder.objects.filter(order__customer=request.user).select_related('seller', 'order')
                               .prefetch_related('items__product', 'items__variant'), invoice_number=invoice)
        resp = render(request, 'storefront/account/invoice.html', {'so': so, 'order': so.order})
        resp['Content-Disposition'] = f'inline; filename="{so.invoice_number}.html"'
        return resp


class AddressListView(LoginRequiredMixin, View):
    def get(self, request):
        return render(request, 'storefront/account/addresses.html', page_ctx(
            request, tab='addresses', addresses=Address.objects.filter(user=request.user)))


class AddressFormView(LoginRequiredMixin, View):
    def _obj(self, request, pk):
        return get_object_or_404(Address, pk=pk, user=request.user) if pk else None

    def _form(self, request, pk, data=None, status=200):
        obj = self._obj(request, pk)
        form = AddressForm(data, instance=obj) if data is not None else AddressForm(instance=obj)
        return form_modal(request, form, title='Edit address' if obj else 'Add address', post_url=request.path,
                          size='md', status=status)

    def get(self, request, pk=None):
        return self._form(request, pk)

    def post(self, request, pk=None):
        obj = self._obj(request, pk)
        form = AddressForm(request.POST, instance=obj)
        if form.is_valid():
            a = form.save(commit=False)
            a.user = request.user
            first = not Address.objects.filter(user=request.user).exists()
            a.is_default = a.is_default or first
            a.save()
            if a.is_default:
                Address.objects.filter(user=request.user).exclude(pk=a.pk).update(is_default=False)
            return done(request, 'Address saved.')
        return self._form(request, pk, request.POST, 422)


class AddressDeleteView(LoginRequiredMixin, View):
    def get(self, request, pk):
        a = get_object_or_404(Address, pk=pk, user=request.user)
        return confirm(request, title='Delete address', message=f'Delete the address for {a.name}?',
                       consequence='Past orders keep their own copy of this address.', confirm_label='Delete', post_url=request.path)

    def post(self, request, pk):
        get_object_or_404(Address, pk=pk, user=request.user).delete()
        return done(request, 'Address deleted.')


class SubscriptionListView(LoginRequiredMixin, View):
    def get(self, request):
        subs = Subscription.objects.filter(user=request.user).select_related('variant__product', 'variant__seller')
        return render(request, 'storefront/account/subscriptions.html', page_ctx(request, tab='subscriptions', subs=subs))


class SubscribeView(View):
    """'Subscribe & save' from the product page. Billing is stubbed: nothing is charged."""
    def get(self, request, variant_id):
        if not request.user.is_authenticated:
            from django.shortcuts import redirect
            from django.urls import reverse
            return redirect(reverse('storefront:login-modal'))
        v = get_object_or_404(visible_variants().select_related('product'), pk=variant_id)
        return form_modal(request, FrequencyForm(initial={'frequency_days': 30}), title=f'Subscribe to {v.product.name}',
                          subtitle=f'{v.label}. Billing is not active yet: you will not be charged.',
                          post_url=request.path, submit='Start subscription')

    def post(self, request, variant_id):
        if not request.user.is_authenticated:
            return HttpResponse(status=401)
        v = get_object_or_404(visible_variants(), pk=variant_id)
        form = FrequencyForm(request.POST)
        if not form.is_valid():
            return form_modal(request, form, title='Subscribe', post_url=request.path, status=422)
        days = int(form.cleaned_data['frequency_days'])
        Subscription.objects.create(user=request.user, variant=v, frequency_days=days, next_delivery=date.today() + timedelta(days=days))
        return done(request, 'Subscription started.', redirect_to='/account/subscriptions/')


class SubscriptionActionView(LoginRequiredMixin, View):
    action = ''

    def _sub(self, request, pk):
        return get_object_or_404(Subscription.objects.select_related('variant__product'), pk=pk, user=request.user)

    def get(self, request, pk):
        s = self._sub(request, pk)
        if self.action == 'frequency':
            return form_modal(request, FrequencyForm(initial={'frequency_days': s.frequency_days}), title='Change frequency',
                              post_url=request.path)
        if self.action == 'cancel':
            return confirm(request, title='Cancel subscription', message=f'Cancel your {s.variant.product.name} subscription?',
                           consequence='No further deliveries will be scheduled. This cannot be undone.', confirm_label='Cancel subscription', post_url=request.path)
        verb = 'Pause' if self.action == 'pause' else 'Resume'
        return confirm(request, title=f'{verb} subscription', message=f'{verb} {s.variant.product.name}?', variant='warning', icon='repeat',
                       consequence='Deliveries stop until you resume.' if verb == 'Pause' else 'Deliveries restart from the next date.',
                       confirm_label=verb, post_url=request.path)

    def post(self, request, pk):
        s = self._sub(request, pk)
        if self.action == 'frequency':
            form = FrequencyForm(request.POST)
            if not form.is_valid():
                return form_modal(request, form, title='Change frequency', post_url=request.path, status=422)
            s.frequency_days = int(form.cleaned_data['frequency_days'])
            s.next_delivery = date.today() + timedelta(days=s.frequency_days)
            msg = 'Frequency updated.'
        elif self.action == 'cancel':
            s.status, msg = 'cancelled', 'Subscription cancelled.'
        elif self.action == 'pause':
            s.status, msg = 'paused', 'Subscription paused.'
        else:
            s.status, msg = 'active', 'Subscription resumed.'
        s.save()
        return done(request, msg)

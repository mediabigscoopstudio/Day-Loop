"""
Seller orders. A seller only ever sees their own SellerOrders (one per seller inside a customer
checkout), never another seller's items. Status changes happen in confirmation popups.
"""
from datetime import date

from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import render
from django.utils import timezone
from django.views import View

from catalog.models import Product
from dash.listing import apply_sort, clean_params, paginate
from orders.models import SellerOrder
from orders.services import seller_flow as flow

from .access import ApprovedSellerMixin
from .base import ApprovedPageView
from .views_variants import trigger

S = SellerOrder.Status
SORTS = {'invoice': 'invoice_number', 'placed': 'created_at', 'amount': 'purchase_value', 'status': 'status'}
KEYS = ['status', 'q', 'product', 'date_from', 'date_to']


def _date(v):
    try:
        return date.fromisoformat(v)
    except (TypeError, ValueError):
        return None


def scoped_orders(seller):
    return SellerOrder.objects.filter(seller=seller).select_related('order__customer')


class OrderListView(ApprovedPageView):
    template_name = 'seller/orders.html'
    active = 'orders'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        p = clean_params(self.request.GET, KEYS)
        counts = SellerOrder.objects.filter(seller=self.seller).aggregate(all=Count('id'), **{s.value: Count('id', filter=Q(status=s)) for s in S})
        qs = scoped_orders(self.seller).annotate(item_count=Count('items'))
        if p.get('status') in S.values:
            qs = qs.filter(status=p['status'])
        if p.get('q'):
            qs = qs.filter(Q(invoice_number__icontains=p['q']) | Q(order__number__icontains=p['q']))
        if p.get('product', '').isdigit():
            qs = qs.filter(items__product_id=int(p['product'])).distinct()
        if (d := _date(p.get('date_from'))):
            qs = qs.filter(created_at__date__gte=d)
        if (d := _date(p.get('date_to'))):
            qs = qs.filter(created_at__date__lte=d)
        qs, sort, desc = apply_sort(qs, self.request.GET, SORTS, ['-created_at'])
        ctx.update(
            page=paginate(qs, self.request.GET), f=p, has_filters=bool(p), counts=counts, now=timezone.now(),
            tabs=[('', 'All', counts['all'])] + [(s.value, s.label, counts[s.value]) for s in S],
            products=Product.objects.filter(seller=self.seller).order_by('name').only('id', 'name'))
        return ctx


class OrderScoped(ApprovedSellerMixin, View):
    def so(self, pk):
        try:
            return scoped_orders(self.seller).get(pk=pk)
        except SellerOrder.DoesNotExist:
            raise Http404


def available_actions(so):
    acts = []
    nxt = flow.next_status(so)
    if nxt:
        acts.append(('advance', {S.ACCEPTED: 'Accept order', S.PACKED: 'Mark packed', S.SHIPPED: 'Ship order', S.DELIVERED: 'Mark delivered'}[nxt]))
    if flow.can_cancel(so):
        acts.append(('cancel', 'Cancel'))
    if flow.can_return(so):
        acts.append(('return', 'Mark returned'))
    return acts


class OrderDetailModal(OrderScoped):
    def get(self, request, pk):
        so = self.so(pk)
        items = list(so.items.select_related('variant', 'product'))
        return render(request, 'seller/orders/detail_modal.html', {
            'so': so, 'order': so.order, 'items': items, 'events': so.events.select_related('actor'),
            'actions': available_actions(so), 'modal_size': 'lg', 'now': timezone.now(),
            'total_qty': sum(i.quantity for i in items)})


class AdvanceView(OrderScoped):
    COPY = {
        S.ACCEPTED: ('Accept this order?', 'You commit to packing and shipping it. Stock stays reserved for the customer.', 'check'),
        S.PACKED: ('Mark as packed?', 'Use this when the package is sealed and ready for the courier.', 'box'),
        S.DELIVERED: ('Mark as delivered?', 'Your payout for this order is credited to your earnings.', 'truck'),
    }

    def get(self, request, pk):
        so = self.so(pk)
        nxt = flow.next_status(so)
        if nxt is None:
            return render(request, 'seller/orders/not_actionable.html', {'so': so, 'modal_size': 'sm'})
        if nxt == S.SHIPPED:
            return render(request, 'seller/orders/ship_modal.html', {'so': so, 'modal_size': 'md', 'sheet': True, 'values': {}})
        msg, cons, icon = self.COPY[nxt]
        return render(request, 'ui/confirm_modal.html', {
            'modal_size': 'sm', 'variant': 'neutral', 'icon': icon, 'title': nxt.label, 'message': f'{msg} {so.invoice_number}', 'consequence': cons,
            'confirm_label': nxt.label, 'post_url': f'/orders/{so.pk}/advance/'})

    def post(self, request, pk):
        so = self.so(pk)
        ship = flow.next_status(so) == S.SHIPPED
        values = {k: request.POST.get(k, '').strip() for k in ('courier', 'awb', 'tracking_url')}
        try:
            if ship and values['tracking_url'] and not values['tracking_url'].lower().startswith(('http://', 'https://')):
                raise flow.FlowError('Tracking link must start with http:// or https://.')
            done = flow.advance(self.seller, so.pk, request.user, **values)
        except flow.FlowError as e:
            tpl = 'seller/orders/ship_modal.html' if ship else 'seller/orders/not_actionable.html'
            return render(request, tpl, {'so': so, 'modal_size': 'md', 'sheet': True, 'values': values, 'error': str(e)}, status=422)
        return trigger(f'{done.invoice_number} is now {done.get_status_display().lower()}.', events=('orders-changed',))


class ReasonedView(OrderScoped):
    """Cancel and return both need a reason."""
    action = 'cancel'
    title, danger_text, label = 'Cancel order', 'The customer’s items go back on your shelf. This cannot be undone.', 'Cancel order'

    def _ctx(self, so, **extra):
        return {'modal_size': 'sm', 'variant': 'danger', 'icon': 'alert', 'title': self.title, 'message': f'{self.title}: {so.invoice_number}?',
                'consequence': self.danger_text, 'confirm_label': self.label, 'post_url': f'/orders/{so.pk}/{self.action}/',
                'reason': True, 'reason_label': 'Reason', **extra}

    def get(self, request, pk):
        return render(request, 'ui/confirm_modal.html', self._ctx(self.so(pk)))

    def post(self, request, pk):
        so = self.so(pk)
        reason = request.POST.get('reason', '').strip()
        if not reason:
            return render(request, 'ui/confirm_modal.html', self._ctx(so, reason_error='A reason is required.'), status=422)
        try:
            done = getattr(flow, 'cancel' if self.action == 'cancel' else 'mark_returned')(self.seller, so.pk, request.user, reason)
        except flow.FlowError as e:
            return render(request, 'ui/confirm_modal.html', self._ctx(so, form_error=str(e), reason_value=reason), status=422)
        return trigger(f'{done.invoice_number} {done.get_status_display().lower()}.', events=('orders-changed',))


class CancelView(ReasonedView):
    action = 'cancel'


class ReturnView(ReasonedView):
    action = 'return'
    title, danger_text, label = 'Mark as returned', 'Stock returns to your inventory and the payout for this order is reversed.', 'Mark returned'


class PackingSlipView(OrderScoped):
    """Printable packing slip for one SellerOrder (this seller's items only)."""

    def get(self, request, pk):
        so = self.so(pk)
        items = list(so.items.select_related('variant', 'product'))
        return render(request, 'seller/orders/packing_slip.html', {
            'so': so, 'order': so.order, 'items': items, 'seller': self.seller,
            'taxable': sum((i.line_total for i in items), 0), 'gst': sum((i.gst_amount for i in items), 0)})


class LabelSheetView(OrderScoped):
    """Shipping label data sheet: to/from, weight, units, courier and AWB."""

    def get(self, request, pk):
        so = self.so(pk)
        items = list(so.items.select_related('variant', 'product'))
        return render(request, 'seller/orders/label.html', {
            'so': so, 'order': so.order, 'items': items, 'seller': self.seller, 'units': sum(i.quantity for i in items),
            'from_address': self.seller.dispatch_address or self.seller.address})

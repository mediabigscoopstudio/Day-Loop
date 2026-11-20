from datetime import date

from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, render
from django.views import View

from orders.models import Order
from sellers.models import SellerProfile

from .access import SuperuserRequiredMixin
from .base import DashPageView
from .htmx import trigger_response
from .listing import apply_sort, clean_params, paginate
from .services.order_status import TransitionError, can_cancel, change_status, next_statuses

SORTS = {'number': 'number', 'customer': 'customer__username', 'total': 'total', 'status': 'status', 'placed': 'placed_at'}
KEYS = ['q', 'status', 'payment', 'seller', 'date_from', 'date_to']


def _date(v):
    try:
        return date.fromisoformat(v)
    except (TypeError, ValueError):
        return None


class OrderListView(DashPageView):
    active = 'orders'
    template_name = 'dash/orders.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        p = clean_params(self.request.GET, KEYS)
        qs = Order.objects.select_related('customer').annotate(item_count=Count('items'))
        if p.get('q'):
            q = p['q']
            qs = qs.filter(Q(number__icontains=q) | Q(customer__username__icontains=q) | Q(customer__email__icontains=q)
                           | Q(customer__first_name__icontains=q) | Q(customer__last_name__icontains=q))
        if p.get('status') in Order.Status.values:
            qs = qs.filter(status=p['status'])
        if p.get('payment') in Order.PaymentStatus.values:
            qs = qs.filter(payment_status=p['payment'])
        if p.get('seller', '').isdigit():
            qs = qs.filter(items__seller_id=int(p['seller'])).distinct()
        if (d := _date(p.get('date_from'))):
            qs = qs.filter(placed_at__date__gte=d)
        if (d := _date(p.get('date_to'))):
            qs = qs.filter(placed_at__date__lte=d)
        qs, sort, desc = apply_sort(qs, self.request.GET, SORTS, ['-placed_at'])
        ctx.update(
            page=paginate(qs, self.request.GET), f=p, has_filters=bool(p),
            statuses=Order.Status.choices, payments=Order.PaymentStatus.choices,
            sellers=SellerProfile.objects.order_by('business_name').only('id', 'business_name'),
        )
        return ctx


def _order(pk):
    return get_object_or_404(Order.objects.select_related('customer'), pk=pk)


class OrderDetailModal(SuperuserRequiredMixin, View):
    def get(self, request, pk):
        order = _order(pk)
        items = list(order.items.select_related('product', 'seller'))
        subs = {}
        for it in items:                                  # per-seller sub-orders (a handful of rows)
            sub = subs.setdefault(it.seller_id, {'seller': it.seller, 'items': [], 'total': 0})
            sub['items'].append(it)
            sub['total'] += it.line_total
        return render(request, 'dash/orders/detail_modal.html', {
            'order': order, 'subs': list(subs.values()), 'modal_size': 'lg',
            'next': next_statuses(order), 'can_cancel': can_cancel(order),
        })


class OrderStatusView(SuperuserRequiredMixin, View):
    def _render(self, request, order, status=200, **extra):
        return render(request, 'dash/orders/status_modal.html',
                      {'order': order, 'next': next_statuses(order), 'modal_size': 'sm', **extra}, status=status)

    def get(self, request, pk):
        return self._render(request, _order(pk))

    def post(self, request, pk):
        order = _order(pk)
        new = request.POST.get('status', '')
        try:
            order = change_status(pk, new)
        except TransitionError as e:
            return self._render(request, order, status=422, form_error=str(e))
        return trigger_response(f'Order #{order.number} marked {order.get_status_display().lower()}.', events=('orders-changed',))


class OrderCancelView(SuperuserRequiredMixin, View):
    def _ctx(self, order, **extra):
        return {'modal_size': 'sm', 'variant': 'danger', 'icon': 'alert', 'title': 'Cancel order',
                'message': f'Cancel order #{order.number}?',
                'consequence': 'Cancelled orders are excluded from revenue and cannot be reopened.',
                'confirm_label': 'Cancel order', 'post_url': f'/orders/{order.pk}/cancel/', **extra}

    def get(self, request, pk):
        return render(request, 'ui/confirm_modal.html', self._ctx(_order(pk)))

    def post(self, request, pk):
        order = _order(pk)
        try:
            order = change_status(pk, None, cancel=True)
        except TransitionError as e:
            return render(request, 'ui/confirm_modal.html', self._ctx(order, form_error=str(e)), status=422)
        return trigger_response(f'Order #{order.number} cancelled.', level='success', events=('orders-changed',))

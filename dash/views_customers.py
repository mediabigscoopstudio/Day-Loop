from django.contrib.auth import get_user_model
from django.db.models import Count, DecimalField, Max, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, render
from django.views import View

from orders.models import Order

from .access import SuperuserRequiredMixin
from .base import DashPageView
from .listing import apply_sort, clean_params, paginate

User = get_user_model()
LIVE = ~Q(orders__status=Order.Status.CANCELLED)
SORTS = {'name': 'username', 'orders': 'order_count', 'ltv': 'lifetime_value', 'last': 'last_order'}


def customers_queryset():
    """Users who have placed at least one order, with their order stats (one query)."""
    return User.objects.annotate(
        order_count=Count('orders', filter=LIVE),
        lifetime_value=Coalesce(Sum('orders__total', filter=LIVE), Value(0), output_field=DecimalField(max_digits=14, decimal_places=2)),
        last_order=Max('orders__placed_at'),
        all_orders=Count('orders'),
    ).filter(all_orders__gte=1)


class CustomerListView(DashPageView):
    active = 'customers'
    template_name = 'dash/customers.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        p = clean_params(self.request.GET, ['q', 'repeat'])
        qs = customers_queryset()
        if p.get('q'):
            q = p['q']
            qs = qs.filter(Q(username__icontains=q) | Q(email__icontains=q) | Q(first_name__icontains=q) | Q(last_name__icontains=q))
        if p.get('repeat') == 'yes':
            qs = qs.filter(order_count__gte=2)
        elif p.get('repeat') == 'no':
            qs = qs.filter(order_count__lt=2)
        qs, sort, desc = apply_sort(qs, self.request.GET, SORTS, ['-last_order'])
        ctx.update(page=paginate(qs, self.request.GET), f=p, has_filters=bool(p))
        return ctx


class CustomerDetailModal(SuperuserRequiredMixin, View):
    def get(self, request, pk):
        customer = get_object_or_404(customers_queryset(), pk=pk)
        recent = Order.objects.filter(customer=customer).annotate(item_count=Count('items')).order_by('-placed_at')[:8]
        aov = (customer.lifetime_value / customer.order_count) if customer.order_count else 0
        return render(request, 'dash/customers/detail_modal.html', {
            'customer': customer, 'recent': recent, 'aov': aov, 'modal_size': 'md'})

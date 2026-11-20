"""Order status transitions. Cancelling has its own warning popup."""
from django.db import transaction

from orders.models import Order

S = Order.Status
NEXT = {
    S.PENDING: [S.PROCESSING],
    S.PROCESSING: [S.SHIPPED],
    S.SHIPPED: [S.DELIVERED],
    S.DELIVERED: [],
    S.CANCELLED: [],
}
CANCELLABLE = {S.PENDING, S.PROCESSING}


class TransitionError(Exception):
    pass


def next_statuses(order):
    return NEXT.get(order.status, [])


def can_cancel(order):
    return order.status in CANCELLABLE


@transaction.atomic
def change_status(order_id, new_status, cancel=False):
    order = Order.objects.select_for_update().get(pk=order_id)
    if cancel:
        if not can_cancel(order):
            raise TransitionError(f'A {order.get_status_display().lower()} order can no longer be cancelled.')
        order.status = S.CANCELLED
    else:
        if new_status not in [s.value for s in next_statuses(order)]:
            raise TransitionError(f'An order that is {order.get_status_display().lower()} cannot move to “{new_status}”.')
        order.status = new_status
    order.save(update_fields=['status'])
    return order

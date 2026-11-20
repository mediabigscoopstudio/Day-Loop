"""
SellerOrder status pipeline:

    New -> Accepted -> Packed -> Shipped -> Delivered
    New / Accepted / Packed -> Cancelled      (stock goes back, nothing credited)
    Delivered -> Returned                      (stock goes back, payout is debited)

Every step writes a timeline event. Credits and debits go to the payout ledger per
SellerOrder. Cancelling or returning one SellerOrder never touches its siblings.
Every function takes the acting `seller` and looks the order up with seller=seller,
so another seller's id raises DoesNotExist (a 404 in the views).
"""
from django.db import transaction
from django.utils import timezone

from catalog.services.stock import return_stock
from orders.models import LedgerEntry, SellerOrder, SellerOrderEvent

S = SellerOrder.Status

NEXT = {
    S.NEW: [S.ACCEPTED],
    S.ACCEPTED: [S.PACKED],
    S.PACKED: [S.SHIPPED],
    S.SHIPPED: [S.DELIVERED],
}
CANCELLABLE = {S.NEW, S.ACCEPTED, S.PACKED}


class FlowError(Exception):
    """Safe-to-show rule violation."""


def next_status(so):
    nxt = NEXT.get(so.status)
    return nxt[0] if nxt else None


def can_cancel(so):
    return so.status in CANCELLABLE


def can_return(so):
    return so.status == S.DELIVERED


def _lock(seller, pk):
    return SellerOrder.objects.select_for_update().select_related('order', 'seller').get(pk=pk, seller=seller)


def _event(so, status, note, actor):
    SellerOrderEvent.objects.create(seller_order=so, status=status, note=note[:240], actor=actor)


def _lines(so):
    return [(it.variant_id, it.quantity) for it in so.items.all() if it.variant_id]


@transaction.atomic
def advance(seller, pk, actor, *, courier='', awb='', tracking_url=''):
    """Move to the next step. Shipping requires courier and AWB."""
    so = _lock(seller, pk)
    target = next_status(so)
    if target is None:
        raise FlowError(f'A {so.get_status_display().lower()} order cannot move forward.')
    note = ''
    if target == S.SHIPPED:
        if not courier.strip() or not awb.strip():
            raise FlowError('Courier name and AWB / tracking number are required to ship.')
        so.courier, so.awb, so.tracking_url, so.shipped_at = courier.strip(), awb.strip(), tracking_url.strip(), timezone.now()
        note = f'Shipped via {so.courier}, AWB {so.awb}'
    if target == S.DELIVERED:
        so.delivered_at = timezone.now()
        LedgerEntry.objects.create(
            seller=so.seller, seller_order=so, kind=LedgerEntry.Kind.CREDIT, amount=so.payout,
            description=f'Payout for {so.invoice_number}',
        )
        note = 'Delivered. Payout credited.'
    so.status = target
    so.save()
    _event(so, target, note or f'Marked {target.label.lower()}', actor)
    return so


@transaction.atomic
def cancel(seller, pk, actor, reason=''):
    so = _lock(seller, pk)
    if not can_cancel(so):
        raise FlowError(f'A {so.get_status_display().lower()} order can no longer be cancelled.')
    return_stock(_lines(so), reference=so.invoice_number[:40], reason='Seller order cancelled')
    so.status = S.CANCELLED
    so.save(update_fields=['status'])
    _event(so, S.CANCELLED, reason or 'Cancelled by seller', actor)
    return so


@transaction.atomic
def mark_returned(seller, pk, actor, reason=''):
    """A delivered order comes back: stock returns and the earlier payout credit is reversed."""
    so = _lock(seller, pk)
    if not can_return(so):
        raise FlowError('Only a delivered order can be returned.')
    return_stock(_lines(so), reference=so.invoice_number[:40], reason='Seller order returned')
    LedgerEntry.objects.create(
        seller=so.seller, seller_order=so, kind=LedgerEntry.Kind.DEBIT, amount=so.payout,
        description=f'Refund for {so.invoice_number}',
    )
    so.status = S.RETURNED
    so.save(update_fields=['status'])
    _event(so, S.RETURNED, reason or 'Returned by customer', actor)
    return so


def expire_unaccepted(now=None):
    """Cancel NEW seller orders the seller did not accept in time. Returns how many were cancelled."""
    now = now or timezone.now()
    n = 0
    for pk, seller_id in SellerOrder.objects.filter(status=S.NEW, accept_by__lt=now).values_list('pk', 'seller_id'):
        with transaction.atomic():
            so = SellerOrder.objects.select_for_update().select_related('seller').get(pk=pk)
            if so.status != S.NEW:
                continue
            return_stock(_lines(so), reference=so.invoice_number[:40], reason='Not accepted in time')
            so.status = S.CANCELLED
            so.save(update_fields=['status'])
            _event(so, S.CANCELLED, 'Not accepted within the time limit', None)
            n += 1
    return n

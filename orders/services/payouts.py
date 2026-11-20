"""Seller earnings from the payout ledger, and admin settlement."""
from decimal import Decimal

from django.db import transaction
from django.db.models import DecimalField, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from orders.models import LedgerEntry, Payout

ZERO = Decimal('0.00')
MONEY = DecimalField(max_digits=14, decimal_places=2)
K = LedgerEntry.Kind


def _signed_sum(qs):
    """credits minus debits over a ledger queryset (one aggregate query)."""
    agg = qs.aggregate(
        c=Coalesce(Sum('amount', filter=Q(kind=K.CREDIT)), Value(ZERO), output_field=MONEY),
        d=Coalesce(Sum('amount', filter=Q(kind=K.DEBIT)), Value(ZERO), output_field=MONEY))
    return agg['c'] - agg['d']


def balances(seller):
    """pending = credited minus debited and not yet settled; settled = total paid out."""
    ledger = LedgerEntry.objects.filter(seller=seller)
    pending = _signed_sum(ledger.filter(payout__isnull=True))
    settled = Payout.objects.filter(seller=seller).aggregate(t=Coalesce(Sum('amount'), Value(ZERO), output_field=MONEY))['t']
    return {'pending': pending, 'settled': settled, 'lifetime': pending + settled}


class SettlementError(Exception):
    pass


@transaction.atomic
def settle(seller_id, actor, reference=''):
    """Pay out everything pending for a seller in one batch. Admin side."""
    entries = list(LedgerEntry.objects.select_for_update().filter(seller_id=seller_id, payout__isnull=True))
    if not entries:
        raise SettlementError('There is nothing pending for this seller.')
    total = sum((e.signed_amount for e in entries), ZERO)
    if total <= 0:
        raise SettlementError('The pending balance is not positive, so there is nothing to pay out yet.')
    payout = Payout.objects.create(seller_id=seller_id, amount=total, reference=(reference or '').strip()[:60],
                                   settled_at=timezone.now(), created_by=actor)
    LedgerEntry.objects.filter(pk__in=[e.pk for e in entries]).update(payout=payout)
    return payout

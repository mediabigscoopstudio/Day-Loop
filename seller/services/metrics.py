"""
Seller dashboard numbers. Everything is a database aggregation and is scoped to one seller.

  Revenue (GMV basis)    sum of purchase values of this seller's orders in the period
  Revenue (payout basis) sum of payouts (purchase value - margin - GST on margin)
  Both exclude cancelled and returned shipments.
  Orders                 shipments placed in the period, plus how many are new / accepted / shipped
  Low stock              variants at or below their alert level (right now)
  Payout due             delivered and not yet settled (from the ledger)
"""
from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, DecimalField, F, Q, Sum, Value
from django.db.models.functions import Coalesce, TruncDate, TruncMonth

from catalog.models import Product, ProductVariant
from dash.services.dates import delta_pct
from orders.models import OrderItem, SellerOrder
from orders.services.payouts import balances

ZERO = Decimal('0.00')
MONEY = DecimalField(max_digits=14, decimal_places=2)
S = SellerOrder.Status
BASIS = {'gmv': 'purchase_value', 'payout': 'payout'}


def live(seller, dr):
    """This seller's shipments placed in the range, excluding cancelled and returned ones."""
    return (SellerOrder.objects.filter(seller=seller, created_at__gte=dr.start, created_at__lt=dr.end)
            .exclude(status__in=[S.CANCELLED, S.RETURNED]))


def _basis(value):
    return value if value in BASIS else 'gmv'


def _numbers(seller, dr):
    agg = live(seller, dr).aggregate(
        gmv=Coalesce(Sum('purchase_value'), Value(ZERO), output_field=MONEY),
        payout=Coalesce(Sum('payout'), Value(ZERO), output_field=MONEY),
        orders=Count('id'), new=Count('id', filter=Q(status=S.NEW)),
        accepted=Count('id', filter=Q(status__in=[S.ACCEPTED, S.PACKED])), shipped=Count('id', filter=Q(status=S.SHIPPED)))
    return agg


def low_stock_qs(seller):
    return (ProductVariant.objects.filter(seller=seller, product__status=Product.Status.LIVE, stock__lte=F('low_stock_threshold'))
            .select_related('product'))


def kpis(seller, dr, basis='gmv'):
    basis = _basis(basis)
    cur, prev = _numbers(seller, dr), _numbers(seller, dr.prior)
    key = 'gmv' if basis == 'gmv' else 'payout'

    def ring(c, p):
        top = max(float(c or 0), float(p or 0))
        return round(float(c or 0) / top, 3) if top else 0

    low = low_stock_qs(seller).count()
    due = balances(seller)['pending']
    return {
        'basis': basis,
        'cards': [
            dict(key='revenue', label='Revenue (GMV)' if basis == 'gmv' else 'Revenue (payout)', icon='rupee', kind='money',
                 value=cur[key], delta=delta_pct(cur[key], prev[key]), ring=ring(cur[key], prev[key])),
            dict(key='orders', label='Orders', icon='cart', kind='int', value=cur['orders'], delta=delta_pct(cur['orders'], prev['orders']),
                 ring=ring(cur['orders'], prev['orders']), note=f'{cur["new"]} new · {cur["accepted"]} accepted · {cur["shipped"]} shipped'),
            dict(key='low_stock', label='Low stock', icon='alert', kind='int', value=low, no_delta=True,
                 ring=0 if not low else 1, note='variants need restocking'),
            dict(key='payout_due', label='Payout due', icon='bag', kind='money', value=due, no_delta=True,
                 ring=0, note='delivered, not yet settled'),
        ],
    }


def _bucket(dr, field):
    return TruncDate(field) if dr.granularity == 'day' else TruncMonth(field)


def _sequence(dr):
    out, d = [], dr.start_date
    if dr.granularity == 'day':
        while d <= dr.end_date:
            out.append(d); d += timedelta(days=1)
    else:
        d = d.replace(day=1)
        while d <= dr.end_date:
            out.append(d); d = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
    return out


def sales_series(seller, dr, basis='gmv'):
    field = BASIS[_basis(basis)]
    rows = live(seller, dr).annotate(b=_bucket(dr, 'created_at')).values('b').annotate(total=Sum(field)).order_by('b')
    by = {(r['b'].date() if hasattr(r['b'], 'date') else r['b']): r['total'] for r in rows}
    fmt = '%b %-d' if dr.granularity == 'day' else '%b %Y'
    seq = _sequence(dr)
    return {'labels': [d.strftime(fmt) for d in seq], 'gmv': [float(by.get(d, 0)) for d in seq]}


def top_products(seller, dr, limit=5):
    return list(
        OrderItem.objects.filter(seller_order__in=live(seller, dr)).values('product', name=F('product__name'))
        .annotate(revenue=Sum('line_total'), units=Sum('quantity')).order_by('-revenue')[:limit])


def needs_action(seller, limit=5):
    """New shipments waiting for the seller to accept, oldest first."""
    return list(SellerOrder.objects.filter(seller=seller, status=S.NEW).select_related('order__customer').annotate(item_count=Count('items'))
                .order_by('accept_by', 'created_at')[:limit])

"""
Dashboard aggregations. Everything is computed in the database (aggregate /
annotate / TruncDate); Python only fills empty buckets for charts and merges
the handful of rows that are displayed.

Definitions
  GMV              sum of order totals, cancelled orders excluded
  Orders           count of non-cancelled orders
  Active sellers   approved sellers with at least one non-cancelled order in the period
  Pending          sellers awaiting a decision now; delta compares applications received
  Repeat customers customers who ordered in the period and have 2+ orders up to its end
  AOV              GMV / Orders
"""
from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, DecimalField, Exists, F, OuterRef, Q, Subquery, Sum
from django.db.models.functions import Coalesce, TruncDate, TruncMonth

from orders.models import Order, OrderItem
from sellers.models import SellerProfile

from .dates import delta_pct

ZERO = Decimal('0')
MONEY = DecimalField(max_digits=14, decimal_places=2)


def live_orders(dr):
    """Non-cancelled orders placed inside the date range."""
    return Order.objects.filter(placed_at__gte=dr.start, placed_at__lt=dr.end).exclude(
        status=Order.Status.CANCELLED
    )


def live_items(dr):
    return OrderItem.objects.filter(
        order__placed_at__gte=dr.start, order__placed_at__lt=dr.end
    ).exclude(order__status=Order.Status.CANCELLED)


def _period_numbers(dr):
    agg = live_orders(dr).aggregate(gmv=Coalesce(Sum('total'), ZERO, output_field=MONEY), orders=Count('id'))
    gmv, orders = agg['gmv'], agg['orders']
    active = live_items(dr).values('seller').distinct().count()
    period_customers = live_orders(dr).values('customer')
    repeat = (
        Order.objects.filter(customer__in=period_customers, placed_at__lt=dr.end)
        .exclude(status=Order.Status.CANCELLED)
        .values('customer').annotate(c=Count('id')).filter(c__gte=2).count()
    )
    applied = SellerProfile.objects.filter(applied_at__gte=dr.start, applied_at__lt=dr.end).count()
    return {
        'gmv': gmv, 'orders': orders, 'active_sellers': active, 'repeat': repeat,
        'aov': (gmv / orders) if orders else ZERO, 'applications': applied,
    }


def _ring(current, prior):
    top = max(float(current or 0), float(prior or 0))
    return round(float(current or 0) / top, 3) if top else 0


def overview_kpis(dr):
    cur, prev = _period_numbers(dr), _period_numbers(dr.prior)
    pending_now = SellerProfile.objects.filter(status=SellerProfile.Status.PENDING).count()

    def card(key, label, icon, value, c, p, kind='int'):
        d = delta_pct(c, p)
        return {'key': key, 'label': label, 'icon': icon, 'value': value, 'kind': kind,
                'delta': d, 'ring': _ring(c, p)}

    return [
        card('gmv', 'GMV', 'rupee', cur['gmv'], cur['gmv'], prev['gmv'], 'money'),
        card('orders', 'Orders', 'cart', cur['orders'], cur['orders'], prev['orders']),
        card('sellers', 'Active Sellers', 'users', cur['active_sellers'], cur['active_sellers'], prev['active_sellers']),
        card('pending', 'Pending Approvals', 'doc', pending_now, cur['applications'], prev['applications']),
        card('repeat', 'Repeat Customers', 'repeat', cur['repeat'], cur['repeat'], prev['repeat']),
        card('aov', 'AOV', 'bag', cur['aov'], cur['aov'], prev['aov'], 'money'),
    ]


def _bucket_sequence(dr):
    """Every bucket start (date) across the range, so charts show zeros for empty days."""
    out, d = [], dr.start_date
    if dr.granularity == 'day':
        while d <= dr.end_date:
            out.append(d)
            d += timedelta(days=1)
    else:
        d = d.replace(day=1)
        while d <= dr.end_date:
            out.append(d)
            d = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
    return out


def _trunc(dr, field):
    return TruncDate(field) if dr.granularity == 'day' else TruncMonth(field)


def sales_series(dr):
    rows = (
        live_orders(dr).annotate(b=_trunc(dr, 'placed_at')).values('b')
        .annotate(gmv=Sum('total'), n=Count('id')).order_by('b')
    )
    by = {(r['b'].date() if hasattr(r['b'], 'date') else r['b']): r for r in rows}
    labels, gmv, orders = [], [], []
    fmt = '%b %-d' if dr.granularity == 'day' else '%b %Y'
    for b in _bucket_sequence(dr):
        r = by.get(b)
        labels.append(b.strftime(fmt))
        gmv.append(float(r['gmv']) if r else 0)
        orders.append(r['n'] if r else 0)
    return {'labels': labels, 'gmv': gmv, 'orders': orders}


def category_revenue(dr, level='category', limit=5):
    """Revenue by top-level category (or by subcategory with level='subcategory')."""
    field = 'product__subcategory__parent__name' if level == 'category' else 'product__subcategory__name'
    rows = list(
        live_items(dr).values(name=F(field)).annotate(revenue=Sum('line_total')).order_by('-revenue')
    )
    total = sum((r['revenue'] for r in rows), ZERO)
    head, tail = rows[:limit], rows[limit:]
    if tail:
        head.append({'name': 'Other', 'revenue': sum((r['revenue'] for r in tail), ZERO)})
    for r in head:
        r['share'] = round(float(r['revenue'] / total * 100), 1) if total else 0
        r['revenue'] = float(r['revenue'])
    return {'rows': head, 'total': float(total)}


def top_sellers(dr, limit=4):
    rows = list(
        live_items(dr).values('seller', name=F('seller__business_name'))
        .annotate(gmv=Sum('line_total'), orders=Count('order', distinct=True))
        .order_by('-gmv')[:limit]
    )
    ids = [r['seller'] for r in rows]
    prior = dict(
        live_items(dr.prior).filter(seller__in=ids).values_list('seller').annotate(g=Sum('line_total'))
    ) if ids else {}
    for r in rows:
        r['growth'] = delta_pct(r['gmv'], prior.get(r['seller'], 0))
    return rows


def pending_sellers(limit=4):
    return list(
        SellerProfile.objects.filter(status=SellerProfile.Status.PENDING)
        .select_related('category').order_by('-applied_at')[:limit]
    )


def recent_orders(limit=5):
    first_seller = OrderItem.objects.filter(order=OuterRef('pk')).order_by('id').values('seller__business_name')[:1]
    return list(
        Order.objects.select_related('customer')
        .annotate(item_count=Count('items'), seller_count=Count('items__seller', distinct=True),
                  first_seller=Subquery(first_seller))
        .order_by('-placed_at')[:limit]
    )


# ---------------------------- analytics ----------------------------

def new_vs_repeat(dr):
    """Per-bucket orders split into first-ever orders (new customers) and later orders (repeat)."""
    first_at = Subquery(
        Order.objects.filter(customer=OuterRef('customer')).exclude(status=Order.Status.CANCELLED)
        .order_by('placed_at').values('placed_at')[:1]
    )
    rows = (
        live_orders(dr).annotate(first_at=first_at, b=_trunc(dr, 'placed_at')).values('b')
        .annotate(new=Count('id', filter=Q(placed_at=F('first_at'))),
                  repeat=Count('id', filter=~Q(placed_at=F('first_at'))))
        .order_by('b')
    )
    by = {(r['b'].date() if hasattr(r['b'], 'date') else r['b']): r for r in rows}
    fmt = '%b %-d' if dr.granularity == 'day' else '%b %Y'
    labels, new, rep = [], [], []
    for b in _bucket_sequence(dr):
        r = by.get(b)
        labels.append(b.strftime(fmt)); new.append(r['new'] if r else 0); rep.append(r['repeat'] if r else 0)
    return {'labels': labels, 'new': new, 'repeat': rep}


def top_products(dr, limit=8):
    return list(
        live_items(dr).values('product', name=F('product__name'), seller_name=F('seller__business_name'))
        .annotate(revenue=Sum('line_total'), units=Sum('quantity')).order_by('-revenue')[:limit]
    )


def repeat_cohorts(limit=12):
    """Customers grouped by month of their first order; how many placed a later order."""
    base = Order.objects.exclude(status=Order.Status.CANCELLED)
    first_at = Subquery(base.filter(customer=OuterRef('customer')).order_by('placed_at').values('placed_at')[:1])
    later = Exists(base.filter(customer=OuterRef('customer'), placed_at__gt=OuterRef('first_at')))
    rows = (
        base.annotate(first_at=first_at).annotate(has_later=later)
        .annotate(cohort=TruncMonth('first_at')).values('cohort')
        .annotate(customers=Count('customer', distinct=True),
                  repeaters=Count('customer', distinct=True, filter=Q(has_later=True)))
        .order_by('-cohort')[:limit]
    )
    out = []
    for r in rows:
        r['rate'] = round(r['repeaters'] / r['customers'] * 100, 1) if r['customers'] else 0
        out.append(r)
    return out

"""URL-driven product filters. Bad input is ignored, never an error."""
from datetime import date
from decimal import Decimal, InvalidOperation

from django.db.models import Q

from catalog.models import Product

LOW_STOCK = 10
FILTER_KEYS = ['q', 'seller', 'category', 'subcategory', 'brand', 'status', 'price_min', 'price_max', 'stock', 'date_from', 'date_to']
STOCK_LEVELS = [('out', 'Out of stock'), ('low', f'Low (1–{LOW_STOCK})'), ('in', 'In stock')]


def _int(v):
    return int(v) if v and v.isdigit() else None


def _dec(v):
    try:
        d = Decimal(v)
        return d if d >= 0 else None
    except (InvalidOperation, TypeError, ValueError):
        return None


def _date(v):
    try:
        return date.fromisoformat(v)
    except (TypeError, ValueError):
        return None


def filter_products(qs, p):
    """p: dict of already-stripped GET values."""
    if p.get('q'):
        q = p['q']
        qs = qs.filter(Q(name__icontains=q) | Q(sku__icontains=q) | Q(brand__icontains=q) | Q(seller__business_name__icontains=q))
    if (v := _int(p.get('seller'))) is not None:
        qs = qs.filter(seller_id=v)
    if (v := _int(p.get('subcategory'))) is not None:
        qs = qs.filter(subcategory_id=v)
    elif (v := _int(p.get('category'))) is not None:
        qs = qs.filter(subcategory__parent_id=v)
    if p.get('brand'):
        qs = qs.filter(brand__iexact=p['brand'])
    if p.get('status') in ('active', 'inactive'):
        qs = qs.filter(is_active=p['status'] == 'active')
    if (v := _dec(p.get('price_min'))) is not None:
        qs = qs.filter(price__gte=v)
    if (v := _dec(p.get('price_max'))) is not None:
        qs = qs.filter(price__lte=v)
    stock = p.get('stock')
    if stock == 'out':
        qs = qs.filter(stock=0)
    elif stock == 'low':
        qs = qs.filter(stock__gte=1, stock__lte=LOW_STOCK)
    elif stock == 'in':
        qs = qs.filter(stock__gt=LOW_STOCK)
    if (v := _date(p.get('date_from'))) is not None:
        qs = qs.filter(created_at__date__gte=v)
    if (v := _date(p.get('date_to'))) is not None:
        qs = qs.filter(created_at__date__lte=v)
    return qs


def base_queryset():
    return Product.objects.select_related('seller', 'subcategory__parent')

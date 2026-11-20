"""URL-driven product filters. Bad input is ignored, never an error."""
from datetime import date
from decimal import Decimal, InvalidOperation

from django.db.models import Exists, Min, OuterRef, Q, Sum
from django.db.models.functions import Coalesce

from catalog.models import Product, ProductVariant

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
        sku_match = Exists(ProductVariant.objects.filter(product=OuterRef('pk'), sku__icontains=q))
        qs = qs.filter(Q(name__icontains=q) | sku_match | Q(brand__icontains=q) | Q(seller__business_name__icontains=q))
    if (v := _int(p.get('seller'))) is not None:
        qs = qs.filter(seller_id=v)
    if (v := _int(p.get('subcategory'))) is not None:
        qs = qs.filter(subcategory_id=v)
    elif (v := _int(p.get('category'))) is not None:
        qs = qs.filter(subcategory__parent_id=v)
    if p.get('brand'):
        qs = qs.filter(brand__iexact=p['brand'])
    status = {'active': 'live'}.get(p.get('status'), p.get('status'))
    if status in Product.Status.values:
        qs = qs.filter(status=status)
    if (v := _dec(p.get('price_min'))) is not None:
        qs = qs.filter(min_price__gte=v)
    if (v := _dec(p.get('price_max'))) is not None:
        qs = qs.filter(min_price__lte=v)
    stock = p.get('stock')
    if stock == 'out':
        qs = qs.filter(total_stock=0)
    elif stock == 'low':
        qs = qs.filter(total_stock__gte=1, total_stock__lte=LOW_STOCK)
    elif stock == 'in':
        qs = qs.filter(total_stock__gt=LOW_STOCK)
    if (v := _date(p.get('date_from'))) is not None:
        qs = qs.filter(created_at__date__gte=v)
    if (v := _date(p.get('date_to'))) is not None:
        qs = qs.filter(created_at__date__lte=v)
    return qs


def base_queryset():
    """Products with their from-price and total stock across variants (one query, no N+1)."""
    return Product.objects.select_related('seller', 'subcategory__parent').annotate(
        min_price=Min('variants__price'), total_stock=Coalesce(Sum('variants__stock'), 0))

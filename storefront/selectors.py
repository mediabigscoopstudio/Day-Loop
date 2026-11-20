"""Catalog read-side. Everything on www goes through visible_products()."""
import re
from decimal import Decimal

from django.db.models import Avg, Count, Exists, Min, OuterRef, Prefetch, Q

from catalog.models import Category, Product, ProductVariant
from sellers.models import SellerProfile

from .models import Review


def visible_variants():
    return ProductVariant.objects.filter(
        is_active=True, stock__gt=0, product__status=Product.Status.LIVE,
        seller__status=SellerProfile.Status.APPROVED,
    )


def visible_products():
    """LIVE products of APPROVED sellers that have at least one in-stock active variant."""
    in_stock = visible_variants().filter(product=OuterRef('pk'))
    return (
        Product.objects.filter(status=Product.Status.LIVE, seller__status=SellerProfile.Status.APPROVED)
        .filter(Exists(in_stock))
        .select_related('seller', 'subcategory', 'subcategory__parent')
        .prefetch_related(
            Prefetch('variants', queryset=ProductVariant.objects.filter(is_active=True).order_by('sort_order', 'price'), to_attr='active_variants'),
            'images',
        )
        .annotate(min_price=Min('variants__price', filter=Q(variants__is_active=True, variants__stock__gt=0)),
                  avg_rating=Avg('reviews__rating'), review_count=Count('reviews', distinct=True))
    )


def pct_off(mrp, price):
    mrp, price = Decimal(mrp or 0), Decimal(price or 0)
    return int(round((mrp - price) / mrp * 100)) if mrp > price > 0 else 0


def decorate(products):
    """Attach display fields (image, default variant, % off, badges) in Python: no extra queries."""
    products = list(products)
    for p in products:
        vs = [v for v in p.active_variants if v.stock > 0] or list(p.active_variants)
        p.default_variant = vs[0] if vs else None
        p.card_variants = p.active_variants[:4]
        imgs = list(p.images.all())
        p.main_image = imgs[0].image if imgs else (p.thumbnail or None)
        v = p.default_variant
        p.off = pct_off(v.mrp, v.price) if v else 0
        p.badges = badges_for(p)
    return products


def badges_for(p):
    out = []
    if (getattr(p, 'review_count', 0) or 0) >= 3 and (p.avg_rating or 0) >= 4.5:
        out.append('Top Rated')
    if p.off >= 25:
        out.append('Value Pack')
    name = p.name.lower()
    if any(k in name for k in ('whey', 'creatine', 'bcaa', 'pre-workout')):
        out.append('Gym Essential')
    return out[:1]


def protein_per_serving(product):
    """Real protein value from the product's own highlights/description, e.g. '24 g protein'."""
    texts = [h.text for h in product.highlights.all()] + [product.short_description, product.description]
    for t in texts:
        m = re.search(r'(\d+(?:\.\d+)?)\s*g\s*(?:of\s*)?protein', t or '', re.I)
        if m:
            return m.group(1)
    return None


def featured_products(n=5):
    qs = visible_products().order_by('-avg_rating', '-created_at')
    return decorate(list(qs[:n]))


def brand_facets(qs):
    return list(qs.values('seller__business_name').annotate(c=Count('id')).order_by('seller__business_name'))


def category_counts():
    cats = list(Category.objects.filter(parent__isnull=True, is_active=True).order_by('sort_order', 'name'))
    counts = {}
    for row in visible_products().values('subcategory__parent_id').annotate(c=Count('id')):
        counts[row['subcategory__parent_id']] = row['c']
    for c in cats:
        c.visible_count = counts.get(c.pk, 0)
    return cats

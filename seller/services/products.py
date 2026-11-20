"""Seller-side product rules. Every function takes the acting `seller`, so another seller's ids never resolve."""
from django.db import transaction
from django.db.models import Min, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone
from django.utils.text import slugify

from catalog.models import Product, ProductHighlight, ProductVariant

from ..richtext import to_text

P = Product.Status
HIGHLIGHTS_MIN, HIGHLIGHTS_MAX = 3, 6
GALLERY_MAX = 8
APLUS_MAX = 5
EDITABLE_STATUSES = {P.DRAFT, P.REJECTED, P.INACTIVE, P.LIVE}


class ProductError(Exception):
    """Safe-to-show rule violation."""


def products_for(seller):
    """The seller's products with from-price and total stock (one query, no N+1)."""
    return (Product.objects.filter(seller=seller).select_related('subcategory__parent')
            .annotate(min_price=Min('variants__price'), total_stock=Coalesce(Sum('variants__stock'), 0)))


def get_product(seller, pk):
    """Raises Product.DoesNotExist for ids that belong to another seller."""
    return Product.objects.select_related('subcategory__parent').get(pk=pk, seller=seller)


def get_variant(seller, product_pk, variant_pk):
    return ProductVariant.objects.select_related('product').get(pk=variant_pk, product_id=product_pk, seller=seller)


def suggest_sku(seller, product, label, exclude_pk=None):
    base = '-'.join(filter(None, [seller.code or 'SLR', slugify(product.name)[:8], slugify(label)[:8]])).upper()
    sku, n = base[:40], 2
    qs = ProductVariant.objects.filter(seller=seller)
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    while qs.filter(sku=sku).exists():
        suffix = f'-{n}'
        sku = base[:40 - len(suffix)] + suffix
        n += 1
    return sku


def variant_problems(v):
    """What stops a variant counting as 'complete' for review."""
    out = []
    if not v.price or v.price <= 0:
        out.append('price')
    if v.stock <= 0:
        out.append('stock')
    if not v.expires_on:
        out.append('expiry date')
    if not v.has_dimensions:
        out.append('package dimensions and weight')
    return out


def autofill_seo(product):
    """Fill empty SEO fields from the name and description (never overwrites what the seller typed)."""
    if not product.meta_title:
        product.meta_title = product.name[:60]
    if not product.meta_description:
        src = product.short_description or to_text(product.description)
        product.meta_description = src[:160]


def readiness(product):
    """Checklist for the editor: five sections, 'N of 5 done'. Returns (sections, done_count, blockers)."""
    variants = list(product.variants.all())
    complete = [v for v in variants if not variant_problems(v)]
    gallery = product.images.count()
    highlights = product.highlights.count()
    sections = [
        dict(key='basics', label='Basics', required=True,
             done=bool(product.name and product.subcategory_id and product.thumbnail),
             hint='Name, category, thumbnail'),
        dict(key='variants', label='Variants', required=True, done=bool(complete),
             hint=f'{len(complete)} of {len(variants)} complete' if variants else 'Add at least one variant'),
        dict(key='media', label='Images & highlights', required=False,
             done=gallery >= 1 and HIGHLIGHTS_MIN <= highlights <= HIGHLIGHTS_MAX,
             hint=f'{gallery} image{"s" if gallery != 1 else ""}, {highlights} highlight{"s" if highlights != 1 else ""} (need {HIGHLIGHTS_MIN}–{HIGHLIGHTS_MAX})'),
        dict(key='seo', label='SEO', required=False, done=bool(product.meta_title and product.meta_description),
             hint='Optional, filled in automatically'),
        dict(key='aplus', label='A+ content', required=False, done=product.aplus_images.exists(), hint='Optional'),
    ]
    blockers = []
    if not product.name:
        blockers.append('Add a product name')
    if not product.subcategory_id:
        blockers.append('Choose a category and subcategory')
    if not product.thumbnail:
        blockers.append('Upload a thumbnail')
    if not variants:
        blockers.append('Add at least one variant')
    elif not complete:
        worst = variant_problems(variants[0])
        blockers.append('Complete a variant: it needs ' + ', '.join(worst))
    return sections, sum(1 for s in sections if s['done']), blockers


@transaction.atomic
def submit_for_review(seller, pk):
    product = Product.objects.select_for_update().get(pk=pk, seller=seller)
    if not seller.is_approved:
        raise ProductError('Your seller account is not approved yet.')
    if product.status not in (P.DRAFT, P.REJECTED):
        raise ProductError(f'A {product.get_status_display().lower()} product cannot be submitted for review.')
    _, _, blockers = readiness(product)
    if blockers:
        raise ProductError('Before submitting: ' + '; '.join(blockers) + '.')
    autofill_seo(product)
    product.status, product.submitted_at, product.rejection_reason = P.PENDING, timezone.now(), ''
    product.save()
    return product


@transaction.atomic
def duplicate(seller, pk):
    """Copy a product as a draft, with its variants (stock reset to 0) and highlights. Images are not copied."""
    src = Product.objects.get(pk=pk, seller=seller)
    copy = Product.objects.create(
        seller=seller, subcategory=src.subcategory, name=f'Copy of {src.name}'[:160], brand=src.brand,
        short_description=src.short_description, description=src.description, status=P.DRAFT,
        meta_keywords=src.meta_keywords,
    )
    for i, v in enumerate(src.variants.all()):
        ProductVariant.objects.create(
            product=copy, seller=seller, label=v.label, sku=suggest_sku(seller, copy, v.label), mrp=v.mrp, price=v.price,
            moq=v.moq, stock=0, low_stock_threshold=v.low_stock_threshold, hsn_code=v.hsn_code, gst_rate=v.gst_rate,
            country_of_origin=v.country_of_origin, dispatch_days=v.dispatch_days, length_cm=v.length_cm, width_cm=v.width_cm,
            height_cm=v.height_cm, weight_g=v.weight_g, sort_order=i,
        )
    for i, h in enumerate(src.highlights.all()):
        ProductHighlight.objects.create(product=copy, text=h.text, sort_order=i)
    return copy


@transaction.atomic
def bulk_set_active(seller, ids, activate):
    """Only live <-> inactive move. Drafts, pending and rejected products are left alone."""
    src, dst = (P.INACTIVE, P.LIVE) if activate else (P.LIVE, P.INACTIVE)
    return Product.objects.filter(seller=seller, pk__in=ids, status=src).update(status=dst, updated_at=timezone.now())

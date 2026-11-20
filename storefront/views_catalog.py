from decimal import Decimal, InvalidOperation

from django.core.paginator import Paginator
from django.db.models import Count, Max, Min, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, render
from django.views import View

from catalog.models import Category, Product
from sellers.models import SellerProfile  # noqa: F401 (used by favourite_brands)
from orders.models import OrderItem

from . import delivery
from .common import is_htmx, page_ctx, popup
from .emi import emi_options
from .selectors import (visible_variants, brand_facets, category_counts, decorate, featured_products, pct_off,
                        protein_per_serving, visible_products)

TIME_SLOTS = {
    'morning': ('Morning', 'Fuel, focus & performance', ('multivitamin', 'shilajit', 'ashwagandha', 'vitamin', 'ginseng')),
    'midday': ('Midday', 'Sustain energy & recover', ('whey', 'protein', 'bcaa', 'eaa', 'creatine')),
    'night': ('Night', 'Rest, repair & build', ('casein', 'magnesium', 'ashwagandha', 'triphala', 'sleep', 'zma')),
}
SORTS = {
    'popular': ('Popularity', ('-review_count', '-created_at')),
    'price_asc': ('Price low to high', ('min_price',)),
    'price_desc': ('Price high to low', ('-min_price',)),
    'newest': ('Newest', ('-created_at',)),
}


def time_q(slot):
    q = Q()
    for kw in TIME_SLOTS[slot][2]:
        q |= Q(name__icontains=kw) | Q(subcategory__name__icontains=kw)
    return q


def favourite_brands(user, n=7):
    """Brands the customer has bought from (most recent first), topped up with the most-stocked approved sellers."""
    from sellers.models import SellerProfile
    from orders.models import SellerOrder
    ids = []
    if user.is_authenticated:
        for sid in SellerOrder.objects.filter(order__customer=user).order_by('-order__placed_at').values_list('seller_id', flat=True):
            if sid not in ids:
                ids.append(sid)
            if len(ids) == n:
                break
    if len(ids) < n:
        top = (SellerProfile.objects.filter(status=SellerProfile.Status.APPROVED, products__status=Product.Status.LIVE,
                                            products__variants__is_active=True, products__variants__stock__gt=0)
               .annotate(c=Count('products', distinct=True)).order_by('-c', 'business_name')
               .values_list('pk', flat=True)[:n * 2])
        for pk in top:
            if pk not in ids and len(ids) < n:
                ids.append(pk)
    found = {
        sp.pk: sp for sp in SellerProfile.objects.filter(pk__in=ids, status=SellerProfile.Status.APPROVED)
        .annotate(c=Count('products', filter=Q(products__status=Product.Status.LIVE), distinct=True))
    }
    from django.contrib.staticfiles import finders
    from django.utils.text import slugify
    out = []
    for i in ids:
        sp = found.get(i)
        if sp and sp.c:
            sp.logo_static = ''
            path = f'storefront/img/brands/{slugify(sp.business_name)}.png'
            if finders.find(path):
                sp.logo_static = path
            out.append(sp)
    return out


class HomeView(View):
    def get(self, request):
        featured = featured_products(5)
        tier = delivery.session_tier(request)
        slots, loop = [], []
        base = visible_products().order_by('-avg_rating', '-created_at')
        for k, v in TIME_SLOTS.items():
            picks = decorate(list(base.filter(time_q(k))[:3])) or decorate(list(base[:3]))  # never an empty bundle
            slots.append({'key': k, 'name': v[0], 'sub': v[1], 'highlight': k == 'midday',
                          'images': [x.main_image for x in picks if x.main_image]})
        loop_day = request.session.get('loop_day', 1)
        chosen = request.session.get('loop_items', {})
        loop = []
        for k, v in TIME_SLOTS.items():
            var = visible_variants().select_related('product', 'seller').filter(pk=chosen.get(k) or 0).first()
            img = None
            if var:
                first = list(var.product.images.all()[:1])
                img = first[0].image if first else (var.product.thumbnail or None)
            loop.append({'key': k, 'name': v[0], 'variant': var, 'image': img})
        loop_total = sum((x['variant'].price for x in loop if x['variant']), Decimal('0'))
        loop_count = sum(1 for x in loop if x['variant'])
        return render(request, 'storefront/home.html', page_ctx(
            request, featured=featured, slots=slots, tier=tier,
            options=delivery.options_for(tier), area=delivery.session_area(request),
            brands=favourite_brands(request.user), loop=loop, loop_total=loop_total, loop_count=loop_count,
            loop_day=loop_day, days=range(1, 29)))


class ProductListView(View):
    def get(self, request):
        qs = visible_products()
        q = request.GET.get('q', '').strip()
        cat_slug = request.GET.get('category', '').strip()
        brands = [b for b in request.GET.getlist('brand') if b]
        slot = request.GET.get('time', '')
        sort = request.GET.get('sort', 'popular')
        if sort not in SORTS:
            sort = 'popular'
        selected = Category.objects.filter(slug=cat_slug, is_active=True).select_related('parent').first() if cat_slug else None
        if selected:
            qs = qs.filter(subcategory=selected) if selected.is_subcategory else qs.filter(subcategory__parent=selected)
        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(seller__business_name__icontains=q) | Q(brand__icontains=q)
                           | Q(subcategory__name__icontains=q))
        if slot in TIME_SLOTS:
            qs = qs.filter(time_q(slot))
        facet_qs = qs  # brand facet counts ignore the brand filter itself
        if brands:
            qs = qs.filter(seller__business_name__in=brands)
        bounds = facet_qs.aggregate(lo=Min('min_price'), hi=Max('min_price'))
        lo_b, hi_b = int(bounds['lo'] or 0), int(bounds['hi'] or 0)
        try:
            pmin = Decimal(request.GET['pmin']) if request.GET.get('pmin') else None
            pmax = Decimal(request.GET['pmax']) if request.GET.get('pmax') else None
        except InvalidOperation:
            pmin = pmax = None
        if pmin is not None:
            qs = qs.filter(min_price__gte=pmin)
        if pmax is not None:
            qs = qs.filter(min_price__lte=pmax)
        qs = qs.order_by(*SORTS[sort][1])
        page = Paginator(qs, 12).get_page(request.GET.get('page'))
        page.object_list = decorate(page.object_list)
        params = request.GET.copy()
        params.pop('page', None)
        title = selected.name if selected else (f'Results for “{q}”' if q else (TIME_SLOTS[slot][0] if slot in TIME_SLOTS else 'All products'))
        ctx = page_ctx(
            request, products=page, total=page.paginator.count, title=title, q=q, selected=selected, sort=sort,
            sorts=[(k, v[0]) for k, v in SORTS.items()], brands=brands, slot=slot, qs_string=params.urlencode(),
            pmin=pmin, pmax=pmax, lo_b=lo_b, hi_b=hi_b, brand_facets=brand_facets(facet_qs),
            categories=category_counts(), in_stock=True,
        )
        tpl = 'storefront/partials/product_results.html' if is_htmx(request) and request.headers.get('HX-Target') == 'results' else 'storefront/product_list.html'
        return render(request, tpl, ctx)


class FiltersSheetView(View):
    """The same filters as a bottom sheet on phones."""
    def get(self, request):
        qs = visible_products()
        return popup(request, 'storefront/modals/filters.html', {
            'categories': category_counts(), 'brand_facets': brand_facets(qs), 'brands': request.GET.getlist('brand'),
            'selected_slug': request.GET.get('category', ''), 'sort': request.GET.get('sort', 'popular'),
            'pmin': request.GET.get('pmin', ''), 'pmax': request.GET.get('pmax', ''), 'q': request.GET.get('q', ''),
            'sorts': [(k, v[0]) for k, v in SORTS.items()],
        })


class SearchView(View):
    """Debounced navbar search: grouped products + brands."""
    def get(self, request):
        q = request.GET.get('q', '').strip()
        products, brands = [], []
        if len(q) >= 2:
            products = decorate(list(visible_products().filter(Q(name__icontains=q) | Q(brand__icontains=q) | Q(seller__business_name__icontains=q))[:6]))
            brands = list(visible_products().filter(seller__business_name__icontains=q)
                          .values('seller__business_name').annotate(c=Count('id')).order_by('seller__business_name')[:4])
        return render(request, 'storefront/partials/search_results.html', {'q': q, 'products': products, 'brands': brands})


class ProductDetailView(View):
    def get(self, request, slug):
        product = get_object_or_404(visible_products().prefetch_related('highlights', 'aplus_images'), slug=slug)
        decorate([product])
        variants = list(product.active_variants)
        sel = None
        if request.GET.get('variant', '').isdigit():
            sel = next((v for v in variants if v.pk == int(request.GET['variant'])), None)
        sel = sel or product.default_variant
        reviews = list(product.reviews.select_related('user')[:10])
        related = decorate(list(visible_products().filter(Q(subcategory=product.subcategory) | Q(seller=product.seller)).exclude(pk=product.pk)[:4]))
        tier = delivery.session_tier(request)
        return render(request, 'storefront/product_detail.html', page_ctx(
            request, product=product, variants=variants, sel=sel, off=pct_off(sel.mrp, sel.price) if sel else 0,
            images=list(product.images.all()), reviews=reviews, related=related, protein=protein_per_serving(product),
            eta=delivery.eta_for(tier, sel.dispatch_days if sel else 0)))


class EmiView(View):
    def get(self, request, variant_id):
        from .selectors import visible_variants
        v = get_object_or_404(visible_variants().select_related('product'), pk=variant_id)
        qty = max(int(request.GET.get('qty', 1) or 1), 1) if request.GET.get('qty', '1').isdigit() else 1
        price = v.price * qty
        return popup(request, 'storefront/modals/emi.html', {'variant': v, 'price': price, 'options': emi_options(price)})

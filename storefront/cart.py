"""Cart. Guests: session. Signed-in: database Cart. On sign-in the session cart merges into the DB cart."""
from collections import OrderedDict
from decimal import Decimal

from django.db import transaction

from catalog.models import ProductVariant

from . import delivery
from .models import Cart, CartItem
from orders.services.money import line_gst
from .selectors import pct_off

SESSION_CART_KEY = 'dayloop_storefront_cart'


def _raw(request):
    if request.user.is_authenticated:
        cart = Cart.objects.filter(user=request.user).first()
        return {str(i.variant_id): i.quantity for i in cart.items.all()} if cart else {}
    return dict(request.session.get(SESSION_CART_KEY, {}))


def _save(request, raw):
    if request.user.is_authenticated:
        cart, _ = Cart.objects.get_or_create(user=request.user)
        with transaction.atomic():
            cart.items.exclude(variant_id__in=[int(k) for k in raw]).delete()
            for vid, qty in raw.items():
                CartItem.objects.update_or_create(cart=cart, variant_id=int(vid), defaults={'quantity': qty})
    else:
        request.session[SESSION_CART_KEY] = raw
        request.session.modified = True


def merge_session_cart(request, user):
    """Call right after login(). Session quantities are added onto the DB cart."""
    raw = request.session.pop(SESSION_CART_KEY, {})
    if not raw:
        return
    cart, _ = Cart.objects.get_or_create(user=user)
    existing = {i.variant_id: i for i in cart.items.all()}
    for vid, qty in raw.items():
        vid = int(vid)
        if vid in existing:
            existing[vid].quantity += int(qty)
            existing[vid].save(update_fields=['quantity'])
        else:
            CartItem.objects.create(cart=cart, variant_id=vid, quantity=int(qty))
    request.session.modified = True


def add_to_cart(request, variant_id, quantity=1):
    raw = _raw(request)
    k = str(int(variant_id))
    raw[k] = raw.get(k, 0) + max(int(quantity), 1)
    _save(request, raw)


def set_cart_quantity(request, variant_id, quantity):
    raw = _raw(request)
    k = str(int(variant_id))
    if int(quantity) <= 0:
        raw.pop(k, None)
    else:
        raw[k] = int(quantity)
    _save(request, raw)


def remove_from_cart(request, variant_id):
    set_cart_quantity(request, variant_id, 0)


def clear_cart(request):
    _save(request, {})


def get_cart(request):
    """Grouped by seller. Lines are never silently trimmed: short stock shows a warning instead."""
    raw = _raw(request)
    ids = [int(k) for k in raw if str(k).isdigit()]
    variants = ProductVariant.objects.select_related('product', 'seller').prefetch_related('product__images').in_bulk(ids)
    tier = delivery.session_tier(request)
    groups = OrderedDict()
    subtotal, gst, count, blocked = Decimal('0'), Decimal('0'), 0, False
    for vid in ids:
        v = variants.get(vid)
        if not v:
            continue
        qty = int(raw[str(vid)])
        ok = v.is_active and v.product.status == 'live' and v.seller.is_approved
        warning = ''
        if not ok or v.stock <= 0:
            warning, blocked = 'No longer available. Remove it to continue.', True
        elif qty > v.stock:
            warning, blocked = f'Only {v.stock} left in stock. Reduce the quantity to continue.', True
        elif qty < v.moq:
            warning, blocked = f'Minimum order quantity is {v.moq}.', True
        imgs = list(v.product.images.all())
        line = {
            'variant': v, 'product': v.product, 'quantity': qty, 'price': v.price, 'mrp': v.mrp,
            'off': pct_off(v.mrp, v.price), 'line_total': v.price * qty, 'warning': warning,
            'image': imgs[0].image if imgs else (v.product.thumbnail or None),
            'eta': delivery.eta_for(tier, v.dispatch_days),
        }
        g = groups.setdefault(v.seller_id, {'seller': v.seller, 'items': [], 'subtotal': Decimal('0'), 'gst': Decimal('0'), 'dispatch_days': 0})
        g['items'].append(line)
        g['subtotal'] += line['line_total']
        g['dispatch_days'] = max(g['dispatch_days'], v.dispatch_days)
        subtotal += line['line_total']
        g['gst'] += line_gst(v.price, qty, v.gst_rate)
        gst += line_gst(v.price, qty, v.gst_rate)
        count += qty
    glist = list(groups.values())
    for i, g in enumerate(glist, 1):
        g['index'], g['count'] = i, len(glist)
        g['eta'] = delivery.eta_for(tier, g['dispatch_days'])
    return {
        'groups': glist, 'items': [l for g in glist for l in g['items']], 'subtotal': subtotal, 'gst': gst,
        'delivery_fee': Decimal('0'), 'total': subtotal + gst, 'total_items': count,
        'line_count': sum(len(g['items']) for g in glist), 'blocked': blocked, 'tier': tier,
    }

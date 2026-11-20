"""
Stock changes. Every change locks the variant row (SELECT ... FOR UPDATE) inside a
transaction, re-reads the stock, and writes a StockMovement. Two concurrent orders can
therefore never oversell the same stock, and stock can never go negative.
"""
from django.db import transaction

from catalog.models import ProductVariant, StockMovement

K = StockMovement.Kind


class InsufficientStock(Exception):
    def __init__(self, variant, wanted):
        self.variant, self.wanted = variant, wanted
        super().__init__(f'Only {variant.stock} of “{variant.product.name} – {variant.label}” left (wanted {wanted}).')


class StockError(Exception):
    pass


def _apply(variant, kind, quantity, actor, reason, reference):
    """Caller must hold the row lock (variant fetched with select_for_update)."""
    old = variant.stock
    if kind in (K.ADD, K.RETURN):
        new = old + quantity
    elif kind in (K.REMOVE, K.SALE):
        if quantity > old:
            raise InsufficientStock(variant, quantity)
        new = old - quantity
    elif kind == K.SET:
        new = quantity
    else:
        raise StockError('Unknown stock action.')
    variant.stock = new
    variant.save(update_fields=['stock'])
    return StockMovement.objects.create(
        variant=variant, kind=kind, delta=new - old, balance_after=new,
        reason=(reason or '')[:160], actor=actor, reference=reference[:40],
    )


def adjust_stock(variant_id, kind, quantity, *, seller=None, actor=None, reason='', reference=''):
    """Add / remove / set stock for one variant. `seller` scopes the lookup (another seller's id -> DoesNotExist)."""
    quantity = int(quantity)
    if quantity < 0:
        raise StockError('Quantity cannot be negative.')
    with transaction.atomic():
        qs = ProductVariant.objects.select_for_update().select_related('product')
        if seller is not None:
            qs = qs.filter(seller=seller)
        variant = qs.get(pk=variant_id)
        _apply(variant, kind, quantity, actor, reason, reference)
        return variant


def take_stock(lines, *, actor=None, reference=''):
    """
    Reserve stock for several lines at once: [(variant_id, quantity), ...].
    Rows are locked in id order so two checkouts never deadlock; either every line is taken or none.
    Must run inside the caller's transaction.atomic block.
    """
    wanted = {}
    for vid, qty in lines:
        wanted[vid] = wanted.get(vid, 0) + int(qty)
    variants = {v.pk: v for v in ProductVariant.objects.select_for_update().select_related('product')
                .filter(pk__in=wanted).order_by('pk')}
    for vid in sorted(wanted):
        v = variants.get(vid)
        if v is None:
            raise StockError('A product in your cart is no longer available.')
        if wanted[vid] < v.moq:
            raise StockError(f'Minimum order quantity for “{v.product.name} – {v.label}” is {v.moq}.')
        _apply(v, K.SALE, wanted[vid], actor, 'Order placed', reference)
    return variants


def return_stock(lines, *, actor=None, reference='', reason='Order cancelled'):
    """Put stock back (cancelled or returned seller order). Runs inside the caller's transaction."""
    for vid, qty in sorted(lines):
        v = ProductVariant.objects.select_for_update().get(pk=vid)
        _apply(v, K.RETURN, int(qty), actor, reason, reference)

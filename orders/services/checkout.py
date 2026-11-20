"""
Multi-seller checkout.

One customer checkout -> one Order (one payment, one address snapshot) which is split
into one SellerOrder per seller. A SellerOrder holds only that seller's items, has its
own invoice number, status, package data and payout line. Sellers never see each other's
items. Stock is taken under row locks in the same transaction.
"""
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from catalog.models import Product, ProductVariant
from catalog.services.stock import InsufficientStock, StockError, take_stock
from orders.models import Order, OrderItem, SellerOrder, SellerOrderEvent
from sellers.models import SellerProfile

from .money import compute_money, line_gst, to_paise

ACCEPT_WINDOW_HOURS = 24


class CheckoutError(Exception):
    """Safe-to-show message for the customer."""


def _next_invoice(seller_id):
    seller = SellerProfile.objects.select_for_update().get(pk=seller_id)
    seller.invoice_seq += 1
    seller.save(update_fields=['invoice_seq'])
    return f'DL-{seller.code}-{seller.invoice_seq:06d}'


@transaction.atomic
def create_order(customer, lines, address=None, payment_method='', payment_status=Order.PaymentStatus.PENDING, now=None):
    """
    lines: [(variant_id, quantity), ...]  address: dict(name, line1, city, state, pincode)
    Returns the Order. Raises CheckoutError (nothing is saved) if any line cannot be fulfilled.
    """
    if not lines:
        raise CheckoutError('Your cart is empty.')
    now = now or timezone.now()
    address = address or {}

    try:
        take_stock([(vid, qty) for vid, qty in lines], reference='checkout')
    except (StockError, InsufficientStock) as e:       # both carry customer-friendly messages
        raise CheckoutError(str(e)) from e

    qty_by_variant = {}
    for vid, qty in lines:
        qty_by_variant[vid] = qty_by_variant.get(vid, 0) + int(qty)

    variants = ProductVariant.objects.select_related('product', 'seller').in_bulk(list(qty_by_variant))
    by_seller = {}
    for vid, qty in qty_by_variant.items():
        v = variants[vid]
        if not v.is_active or v.product.status != Product.Status.LIVE or not v.seller.is_approved:
            raise CheckoutError(f'“{v.product.name} – {v.label}” is not available right now.')
        by_seller.setdefault(v.seller_id, []).append((v, qty))

    order = Order.objects.create(
        customer=customer, placed_at=now, status=Order.Status.PENDING, payment_status=payment_status,
        payment_method=payment_method, total=Decimal('0'),
        ship_name=address.get('name', ''), ship_line1=address.get('line1', ''), ship_city=address.get('city', ''),
        ship_state=address.get('state', ''), ship_pincode=address.get('pincode', ''),
    )

    seller_ids = sorted(by_seller)
    grand_total = Decimal('0')
    for idx, seller_id in enumerate(seller_ids, start=1):
        so = SellerOrder.objects.create(
            order=order, seller_id=seller_id, invoice_number=_next_invoice(seller_id),
            accept_by=now + timedelta(hours=ACCEPT_WINDOW_HOURS), shipment_index=idx, shipment_count=len(seller_ids),
        )
        purchase = Decimal('0')
        gst_total = Decimal('0')
        weight = Decimal('0')
        for v, qty in by_seller[seller_id]:
            taxable = to_paise(v.price * qty)
            gst = line_gst(v.price, qty, v.gst_rate)
            OrderItem.objects.create(
                order=order, seller_order=so, product=v.product, variant=v, seller_id=seller_id,
                quantity=qty, unit_price=v.price, gst_rate=v.gst_rate, gst_amount=gst,
            )
            purchase += taxable
            gst_total += gst
            weight += v.chargeable_kg * qty
        m = compute_money(purchase)
        so.purchase_value, so.commission_rate, so.gst_rate_on_margin = m.purchase_value, m.commission_rate, m.gst_rate_on_margin
        so.margin, so.margin_gst, so.payout = m.margin, m.margin_gst, m.payout
        so.package_weight_kg = weight.quantize(Decimal('0.001'))
        so.save()
        SellerOrderEvent.objects.create(seller_order=so, status=SellerOrder.Status.NEW, note='Order placed')
        grand_total += purchase + gst_total

    order.total = to_paise(grand_total)
    order.save(update_fields=['total'])
    return order


def shipment_labels(order):
    """For the customer checkout: 'Shipment 1 of 3 from <seller>' per seller order."""
    return [f'Shipment {so.shipment_index} of {so.shipment_count} from {so.seller.business_name}'
            for so in order.seller_orders.select_related('seller').order_by('shipment_index')]

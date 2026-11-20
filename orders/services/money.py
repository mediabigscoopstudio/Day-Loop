"""
Platform money rules (applied exactly):

    purchase value = sum of the SellerOrder's item selling prices (taxable value, GST excluded)
    margin         = 5% of the purchase value
    GST on margin  = 18% of the margin only (not of the product value)
    seller payout  = purchase value - margin - GST on margin

    Example: 10,000 -> margin 500 -> GST 90 -> payout 9,410

Rates are stored on each SellerOrder as a snapshot, so later changes never touch old orders.
All maths is Decimal, rounded half-up to paise.
"""
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

PAISE = Decimal('0.01')
COMMISSION_RATE = Decimal('0.0500')
MARGIN_GST_RATE = Decimal('0.1800')


def to_paise(value) -> Decimal:
    return Decimal(value).quantize(PAISE, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class Money:
    purchase_value: Decimal
    commission_rate: Decimal
    gst_rate_on_margin: Decimal
    margin: Decimal
    margin_gst: Decimal
    payout: Decimal


def compute_money(purchase_value, commission_rate=COMMISSION_RATE, gst_rate_on_margin=MARGIN_GST_RATE) -> Money:
    purchase = to_paise(purchase_value)
    commission_rate, gst_rate_on_margin = Decimal(commission_rate), Decimal(gst_rate_on_margin)
    margin = to_paise(purchase * commission_rate)
    margin_gst = to_paise(margin * gst_rate_on_margin)       # GST applies to the margin, not the goods
    payout = purchase - margin - margin_gst
    return Money(purchase, commission_rate, gst_rate_on_margin, margin, margin_gst, payout)


def line_gst(unit_price, quantity, gst_rate_percent):
    """GST collected from the customer on a line (separate from the platform GST above)."""
    taxable = to_paise(Decimal(unit_price) * int(quantity))
    return to_paise(taxable * Decimal(gst_rate_percent) / Decimal(100))

"""Indicative no-cost EMI: price split evenly over the tenure. Snapmint confirms the final plan."""
from decimal import ROUND_HALF_UP, Decimal

TENURES = (3, 6, 9)


def emi_options(price):
    price = Decimal(str(price))
    out = []
    for n in TENURES:
        monthly = (price / n).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
        out.append({'months': n, 'monthly': monthly, 'total': monthly * n})
    return out

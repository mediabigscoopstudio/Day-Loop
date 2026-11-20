from django import template

from storefront import delivery
from storefront.cart import get_cart
from storefront.selectors import category_counts

register = template.Library()


@register.simple_tag(takes_context=True)
def store_shell(context):
    """Navbar/footer data without a context processor (TEMPLATES settings stay untouched)."""
    request = context['request']
    area = delivery.session_area(request)
    tier = delivery.session_tier(request)
    cart = context.get('cart') or get_cart(request)
    return {
        'area': area, 'tier': tier, 'tier_label': delivery.TIER_LABELS[tier],
        'tier_short': {'fastest': '15 min', 'same_day': 'Same day', 'scheduled': 'Scheduled'}.get(tier, 'Scheduled'),
        'cart_count': cart['total_items'], 'nav_categories': category_counts(),
    }


@register.filter
def stars(value):
    try:
        return '★' * int(round(float(value))) + '☆' * (5 - int(round(float(value))))
    except (TypeError, ValueError):
        return ''


@register.filter
def media_url(f):
    try:
        return f.url if f else ''
    except ValueError:
        return ''

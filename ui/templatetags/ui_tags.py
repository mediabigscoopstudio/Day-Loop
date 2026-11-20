from decimal import Decimal, InvalidOperation

from django import template
from django.contrib.staticfiles import finders
from django.templatetags.static import static
from django.utils import timezone
from django.utils.html import format_html
from django.utils.safestring import mark_safe

register = template.Library()


def _to_decimal(value):
    try:
        return Decimal(str(value if value not in (None, '') else 0))
    except (InvalidOperation, ValueError):
        return Decimal(0)


def group_indian(n: int) -> str:
    """12345678 -> '1,23,45,678'."""
    s = str(abs(int(n)))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ','.join(parts + [tail])
    return ('-' if int(n) < 0 else '') + s


@register.filter
def inr(value, decimals=0):
    """₹92,48,320 (Indian digit grouping). Optional decimals: {{ x|inr:2 }}."""
    d = _to_decimal(value)
    decimals = int(decimals)
    q = d.quantize(Decimal(1).scaleb(-decimals)) if decimals else d.quantize(Decimal(1))
    sign = '-' if q < 0 else ''
    q = abs(q)
    whole = int(q)
    out = group_indian(whole)
    if decimals:
        frac = f'{q - Decimal(whole):.{decimals}f}'.split('.')[1]
        out = f'{out}.{frac}'
    return f'{sign}₹{out}'


@register.filter
def inr_short(value):
    """₹1.25 Cr, ₹35.14 L, ₹4,798."""
    d = _to_decimal(value)
    a = abs(d)
    sign = '-' if d < 0 else ''
    if a >= Decimal(10_000_000):
        return f'{sign}₹{a / Decimal(10_000_000):.2f} Cr'
    if a >= Decimal(100_000):
        return f'{sign}₹{a / Decimal(100_000):.2f} L'
    return inr(d)


@register.filter
def intcomma_in(value):
    """3,842 / 1,24,600 (no currency)."""
    return group_indian(int(_to_decimal(value)))


@register.filter
def pct(value, decimals=1):
    d = _to_decimal(value)
    return f'{abs(d):.{int(decimals)}f}%'


@register.simple_tag
def greeting():
    hour = timezone.localtime().hour
    if hour < 12:
        return 'Good morning'
    if hour < 17:
        return 'Good afternoon'
    return 'Good evening'


@register.filter
def first_name(user):
    name = (getattr(user, 'first_name', '') or '').strip()
    return name or getattr(user, 'get_username', lambda: 'there')()


@register.filter
def initials(user_or_text):
    text = getattr(user_or_text, 'get_full_name', lambda: '')() or str(user_or_text)
    parts = [p for p in text.replace('@', ' ').split() if p]
    return ''.join(p[0] for p in parts[:2]).upper() or 'U'


@register.simple_tag
def dayloop_logo(css_class=''):
    """The Dayloop wordmark file, used as is. Falls back to a text wordmark if missing."""
    path = 'ui/img/logo.png'  # transparent wordmark (original: dayloop-logo.png)
    if finders.find(path):
        return format_html('<img src="{}" alt="Dayloop" class="logo {}">', static(path), css_class)
    return mark_safe('<span class="brand-word">dayloop</span>')


_ICONS = {
    'home': '<path d="M3 11l9-8 9 8"/><path d="M5 10v10h14V10"/>',
    'box': '<path d="M21 8l-9-5-9 5v8l9 5 9-5z"/><path d="M3 8l9 5 9-5M12 13v8"/>',
    'users': '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c.6-3.5 3.2-5.5 6.5-5.5s5.9 2 6.5 5.5"/><path d="M16 4.7a3.5 3.5 0 010 6.6M18 14.8c2 .7 3.2 2.5 3.5 5.2"/>',
    'layers': '<path d="M12 3l9 5-9 5-9-5z"/><path d="M3 13l9 5 9-5"/><path d="M3 17.5l9 5 9-5" opacity=".5"/>',
    'user': '<circle cx="12" cy="8" r="4"/><path d="M4 21c.7-4.2 4-6.5 8-6.5s7.3 2.3 8 6.5"/>',
    'chart': '<path d="M5 20V10M12 20V4M19 20v-7"/>',
    'search': '<circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/>',
    'calendar': '<rect x="3" y="5" width="18" height="16" rx="3"/><path d="M3 10h18M8 3v4M16 3v4"/>',
    'bell': '<path d="M6 17V11a6 6 0 1112 0v6l1.5 2h-15z"/><path d="M10 21h4"/>',
    'menu': '<path d="M4 7h16M4 12h16M4 17h16"/>',
    'rupee': '<path d="M7 5h10M7 9h10M7 5c5 0 6 2 6 4s-2 4-6 4l7 7"/>',
    'cart': '<circle cx="9" cy="20" r="1.5"/><circle cx="18" cy="20" r="1.5"/><path d="M3 4h3l2.4 11h10l2-8H7"/>',
    'doc': '<path d="M7 3h8l4 4v14H7z"/><path d="M14 3v5h5M10 13h6M10 17h6"/>',
    'repeat': '<path d="M17 2l4 4-4 4"/><path d="M3 11V9a3 3 0 013-3h15"/><path d="M7 22l-4-4 4-4"/><path d="M21 13v2a3 3 0 01-3 3H3"/>',
    'bag': '<path d="M5 8h14l-1 12H6z"/><path d="M9 8V6a3 3 0 016 0v2"/>',
    'leaf': '<path d="M5 19c0-9 5-14 15-14 0 10-5 15-14 15"/><path d="M5 19c3-5 6-8 10-10"/>',
    'alert': '<path d="M12 3l10 18H2z"/><path d="M12 10v5M12 18v.5"/>',
    'check': '<circle cx="12" cy="12" r="9"/><path d="M8 12.5l2.7 2.7L16 9.5"/>',
    'x': '<path d="M6 6l12 12M18 6L6 18"/>',
    'trash': '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/>',
    'logout': '<path d="M9 4H5v16h4M16 8l4 4-4 4M20 12H9"/>',
    'inbox': '<path d="M3 13l3-8h12l3 8v6H3z"/><path d="M3 13h5l1 3h6l1-3h5"/>',
    'info': '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5v.5"/>',
    'truck': '<path d="M2 6h12v10H2zM14 10h4l3 3v3h-7"/><circle cx="7" cy="18" r="2"/><circle cx="17" cy="18" r="2"/>',
    'tag': '<path d="M3 12V4h8l10 10-8 8z"/><circle cx="7.5" cy="8.5" r="1.2"/>',
    'plus': '<path d="M12 5v14M5 12h14"/>',
    'edit': '<path d="M4 20h4L19 9l-4-4L4 16z"/>',
}


@register.simple_tag
def icon(name, size=20):
    body = _ICONS.get(name, _ICONS['info'])
    return format_html(
        '<svg width="{0}" height="{0}" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{1}</svg>',
        size, mark_safe(body),
    )


@register.filter
def status_chip(status):
    """CSS class for a status chip."""
    return {
        'approved': 'up', 'delivered': 'up', 'paid': 'up', 'active': 'up', 'shipped': 'up',
        'pending': 'warn', 'processing': 'amber', 'needs_info': 'amber', 'refunded': 'neutral',
        'rejected': 'danger', 'cancelled': 'danger', 'failed': 'danger', 'inactive': 'neutral',
    }.get(str(status), 'neutral')


@register.filter
def get_item(d, key):
    return d.get(key) if hasattr(d, 'get') else None

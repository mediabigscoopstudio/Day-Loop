from urllib.parse import urlencode

from django import template

register = template.Library()


@register.simple_tag(takes_context=True)
def qs(context, **updates):
    """Current query string with updates applied. A value of None/'' removes the key.
    {% qs sort='name' dir='asc' page=None %}"""
    params = context['request'].GET.copy()
    for k, v in updates.items():
        if v in (None, ''):
            params.pop(k, None)
        else:
            params[k] = v
    s = urlencode([(k, v) for k in params for v in params.getlist(k)])
    return f'?{s}' if s else '?'


@register.simple_tag(takes_context=True)
def sort_link(context, key, label):
    """A sortable <th> link that toggles asc/desc."""
    req = context['request']
    cur, desc = req.GET.get('sort'), req.GET.get('dir') == 'desc'
    nxt = 'desc' if (cur == key and not desc) else 'asc'
    arrow = (' ↓' if desc else ' ↑') if cur == key else ''
    from django.utils.html import format_html
    params = req.GET.copy(); params['sort'] = key; params['dir'] = nxt; params.pop('page', None)
    return format_html('<a href="?{}" aria-label="Sort by {}">{}{}</a>', urlencode(params), label, label, arrow)

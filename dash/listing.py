"""Shared helpers for list pages: sorting, pagination, URL-driven filters."""
from django.core.paginator import Paginator

PER_PAGE = 15


def apply_sort(qs, params, allowed, default):
    """allowed: {'name': 'business_name', ...}; ?sort=name&dir=desc. Unknown keys fall back to default."""
    key = params.get('sort')
    direction = '-' if params.get('dir') == 'desc' else ''
    if key in allowed:
        field = allowed[key]
        order = [f'{direction}{f}' for f in (field if isinstance(field, (list, tuple)) else [field])]
        return qs.order_by(*order, '-pk'), key, params.get('dir') == 'desc'
    return qs.order_by(*default), None, False


def paginate(qs, params, per_page=PER_PAGE):
    """get_page() never raises: bad numbers fall back to page 1, too-large ones to the last page."""
    return Paginator(qs, per_page).get_page(params.get('page'))


def clean_params(params, allowed_keys):
    """Only the listed keys survive, so URLs stay predictable."""
    return {k: params.get(k, '').strip() for k in allowed_keys if params.get(k, '').strip()}

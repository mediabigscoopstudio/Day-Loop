"""
Host patterns for django-hosts (ROOT_HOSTCONF = 'dayloop.hosts').

Each host name is joined with PARENT_HOST, so with PARENT_HOST='localhost:8000':

    www.localhost:8000    -> dayloop.urls_www    (customer storefront, default)
    seller.localhost:8000 -> dayloop.urls_seller (seller portal)
    dash.localhost:8000   -> dayloop.urls_dash   (internal admin panel)
    api.localhost:8000    -> dayloop.urls_api    (API and webhooks)

Unknown subdomains fall back to DEFAULT_HOST ('www').
"""
from django_hosts import host, patterns

host_patterns = patterns(
    '',
    host(r'www', 'dayloop.urls_www', name='www'),
    host(r'seller', 'dayloop.urls_seller', name='seller'),
    host(r'dash', 'dayloop.urls_dash', name='dash'),
    host(r'api', 'dayloop.urls_api', name='api'),
)

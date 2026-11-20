"""URLconf for www.<parent> - customer storefront (default host)."""
from django.conf import settings
from django.http import HttpResponse
from django.template import Template, Context
from django.urls import path

from django_hosts.resolvers import reverse

_PAGE = Template(
    "{% load hosts %}"
    "<h1>Day Loop: storefront</h1>"
    "<p>Host: www. Purchases happen here.</p>"
    "<p><a href=\"{% host_url 'seller-home' host 'seller' %}\">Seller portal (host_url tag)</a></p>"
    "<p><a href=\"{{ seller_url }}\">Seller portal (reverse)</a></p>"
)


def home(request):
    seller_url = reverse('seller-home', host='seller', scheme=settings.DJANGO_SCHEME)
    return HttpResponse(_PAGE.render(Context({'seller_url': seller_url})))


urlpatterns = [
    path('', home, name='www-home'),
]

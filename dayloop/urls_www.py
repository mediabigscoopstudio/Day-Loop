"""URLconf for the customer storefront (www.*)."""
from django.http import HttpResponse
from django.urls import path


def home(request):
    return HttpResponse(f"Day Loop storefront (surface={request.surface})")


urlpatterns = [
    path('', home, name='www-home'),
]

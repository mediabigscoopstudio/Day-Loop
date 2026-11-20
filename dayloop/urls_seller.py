"""URLconf for the seller portal (seller.*)."""
from django.http import HttpResponse
from django.urls import path


def home(request):
    return HttpResponse(f"Day Loop seller portal (surface={request.surface})")


urlpatterns = [
    path('', home, name='seller-home'),
]

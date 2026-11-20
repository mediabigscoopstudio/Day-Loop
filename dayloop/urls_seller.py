"""URLconf for seller.<parent> - seller portal."""
from django.http import HttpResponse
from django.urls import path


def home(request):
    return HttpResponse("Day Loop: seller portal")


urlpatterns = [
    path('', home, name='seller-home'),
]

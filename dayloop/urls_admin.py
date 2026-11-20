"""URLconf for the internal admin panel (admin.*)."""
from django.contrib import admin
from django.http import HttpResponse
from django.urls import path


def home(request):
    return HttpResponse(f"Day Loop admin panel (surface={request.surface})")


urlpatterns = [
    path('', home, name='admin-home'),
    path('django/', admin.site.urls),
]

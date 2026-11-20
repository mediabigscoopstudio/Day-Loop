"""URLconf for dash.<parent> - internal admin panel.

Custom panel at the root; Django's built-in admin at /admin/.
"""
from django.contrib import admin
from django.http import HttpResponse
from django.urls import path


def home(request):
    return HttpResponse("Day Loop: internal admin panel")


urlpatterns = [
    path('', home, name='dash-home'),
    path('admin/', admin.site.urls),
]

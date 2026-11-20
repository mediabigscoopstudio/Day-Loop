"""URLconf for dash.<parent> - internal admin panel.

The custom panel lives at the root; Django's built-in admin at /admin/.
Both are protected by dash.middleware.DashAccessMiddleware (superusers only).
"""
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('dash.urls')),
]

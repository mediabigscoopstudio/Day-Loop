"""URLconf for seller.<parent> - the seller portal (see seller/urls.py)."""
from django.conf import settings
from django.conf.urls.static import static
from django.urls import include, path

urlpatterns = [
    path('', include('seller.urls')),
]
# Uploaded logos, documents and product images (development only; use the web server in production).
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

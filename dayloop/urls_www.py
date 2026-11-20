"""URLconf for www.<parent> - customer storefront (default host)."""
from django.conf import settings
from django.conf.urls.static import static
from django.urls import include, path

urlpatterns = [
    path('', include('storefront.urls')),
]

# Serve media files in development for product images and uploads
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

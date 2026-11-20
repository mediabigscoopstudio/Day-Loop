"""URLconf for api.<parent> - API and webhooks (stub)."""
from django.http import JsonResponse
from django.urls import path


def health(request):
    return JsonResponse({'status': 'ok', 'host': 'api'})


urlpatterns = [
    path('health/', health, name='api-health'),
]

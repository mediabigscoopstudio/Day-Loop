from django.urls import path

from . import auth_views, views, views_sellers

urlpatterns = [
    path('login/', auth_views.LoginView.as_view(), name='login'),
    path('logout/confirm/', auth_views.LogoutConfirmView.as_view(), name='logout-confirm'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('', views.OverviewView.as_view(), name='overview'),
    path('partials/kpis/', views.KpiPartial.as_view(), name='partial-kpis'),
    path('partials/pending-approvals/', views.PendingPartial.as_view(), name='partial-pending'),
    path('partials/recent-orders/', views.RecentOrdersPartial.as_view(), name='partial-recent-orders'),
    path('sellers/', views_sellers.SellerListView.as_view(), name='sellers'),
    path('sellers/<int:pk>/', views_sellers.SellerDetailModal.as_view(), name='seller-detail'),
    path('sellers/<int:pk>/<slug:action>/', views_sellers.SellerActionView.as_view(), name='seller-action'),
    path('api/sales/', views.SalesApi.as_view(), name='api-sales'),
    path('api/category-revenue/', views.CategoryRevenueApi.as_view(), name='api-category-revenue'),
]

from django.urls import path

from . import auth_views, views, views_categories, views_products, views_sellers

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
    path('products/', views_products.ProductListView.as_view(), name='products'),
    path('products/bulk/', views_products.ProductBulkView.as_view(), name='products-bulk'),
    path('products/<int:pk>/', views_products.ProductDetailModal.as_view(), name='product-detail'),
    path('products/<int:pk>/toggle/', views_products.ProductToggleView.as_view(), name='product-toggle'),
    path('products/categories/', views_categories.CategoryListView.as_view(), name='categories'),
    path('products/categories/new/', views_categories.CategoryFormView.as_view(), name='category-new'),
    path('products/categories/<int:pk>/edit/', views_categories.CategoryFormView.as_view(), name='category-edit'),
    path('products/categories/<int:pk>/toggle/', views_categories.CategoryToggleView.as_view(), name='category-toggle'),
    path('products/categories/<int:pk>/delete/', views_categories.CategoryDeleteView.as_view(), name='category-delete'),
    path('products/categories/<int:pk>/move/<slug:direction>/', views_categories.CategoryMoveView.as_view(), name='category-move'),
    path('products/subcategory-options/', views_categories.SubcategoryOptions.as_view(), name='subcategory-options'),
    path('api/sales/', views.SalesApi.as_view(), name='api-sales'),
    path('api/category-revenue/', views.CategoryRevenueApi.as_view(), name='api-category-revenue'),
]

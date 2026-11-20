from django.urls import path

from . import auth_views, views

urlpatterns = [
    path('login/', auth_views.LoginView.as_view(), name='login'),
    path('register/', auth_views.RegisterView.as_view(), name='register'),
    path('logout/confirm/', auth_views.LogoutConfirmView.as_view(), name='logout-confirm'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('status/', views.StatusView.as_view(), name='status'),
    path('', views.HomeView.as_view(), name='home'),
]

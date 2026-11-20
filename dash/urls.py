from django.urls import path

from . import auth_views, views

urlpatterns = [
    path('login/', auth_views.LoginView.as_view(), name='login'),
    path('logout/confirm/', auth_views.LogoutConfirmView.as_view(), name='logout-confirm'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('', views.OverviewView.as_view(), name='overview'),
]

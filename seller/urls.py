from django.urls import path

from . import auth_views, views, views_onboarding

urlpatterns = [
    path('login/', auth_views.LoginView.as_view(), name='login'),
    path('register/', auth_views.RegisterView.as_view(), name='register'),
    path('logout/confirm/', auth_views.LogoutConfirmView.as_view(), name='logout-confirm'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('status/', views.StatusView.as_view(), name='status'),
    path('status/reply/', views_onboarding.InfoReplyView.as_view(), name='status-reply'),
    path('onboarding/', views_onboarding.OnboardingView.as_view(), name='onboarding'),
    path('onboarding/step/<int:step>/', views_onboarding.OnboardingStepView.as_view(), name='onboarding-step'),
    path('onboarding/submit/', views_onboarding.OnboardingSubmitView.as_view(), name='onboarding-submit'),
    path('', views.HomeView.as_view(), name='home'),
]

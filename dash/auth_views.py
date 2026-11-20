"""Login (layer 3: rejects non-superusers) and logout with a confirmation popup."""
from django import forms
from django.contrib.auth import authenticate, get_user_model, login, logout
from django.db.models import Q
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View

from .access import (
    SuperuserRequiredMixin, clear_failures, is_dash_admin, is_throttled, record_failure,
)

GENERIC_ERROR = 'Invalid credentials or not authorised'
THROTTLE_ERROR = 'Too many failed attempts. Please try again in a few minutes.'


class LoginForm(forms.Form):
    identifier = forms.CharField(max_length=254, strip=True)
    password = forms.CharField(max_length=256, strip=False)


def safe_next(request, value):
    if value and url_has_allowed_host_and_scheme(
        value, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ) and value.startswith('/') and not value.startswith('//'):
        return value
    return '/'


class LoginView(View):
    template = 'dash/login.html'

    def get(self, request):
        if is_dash_admin(request.user):
            return HttpResponseRedirect(safe_next(request, request.GET.get('next')))
        return render(request, self.template, {'next': request.GET.get('next', '')})

    def post(self, request):
        next_url = request.POST.get('next', '')
        form = LoginForm(request.POST)
        ctx = {'next': next_url}
        if not form.is_valid():
            ctx['error'] = GENERIC_ERROR
            return render(request, self.template, ctx, status=400)

        ident = form.cleaned_data['identifier']
        password = form.cleaned_data['password']
        ctx['identifier'] = ident

        if is_throttled(request, ident):
            ctx['error'] = THROTTLE_ERROR
            return render(request, self.template, ctx, status=429)

        User = get_user_model()
        candidate = User.objects.filter(Q(username__iexact=ident) | Q(email__iexact=ident)).first()
        user = None
        if candidate is not None:
            user = authenticate(request, username=candidate.get_username(), password=password)
        else:
            User().set_password(password)  # keep timing similar when the account does not exist

        if user is None or not is_dash_admin(user):
            record_failure(request, ident)
            ctx['error'] = GENERIC_ERROR  # one message for every failure reason
            return render(request, self.template, ctx, status=400)

        clear_failures(request, ident)
        login(request, user)
        return HttpResponseRedirect(safe_next(request, next_url))


class LogoutConfirmView(SuperuserRequiredMixin, View):
    def get(self, request):
        return render(request, 'ui/confirm_modal.html', {
            'modal_size': 'sm', 'variant': 'warning', 'icon': 'logout',
            'title': 'Log out', 'message': 'Log out of the admin panel?',
            'detail': 'You will need to sign in again to access the dashboard.',
            'confirm_label': 'Log out', 'post_url': '/logout/',
        })


class LogoutView(SuperuserRequiredMixin, View):
    def post(self, request):
        logout(request)
        if request.headers.get('HX-Request') == 'true':
            return HttpResponse(status=204, headers={'HX-Redirect': '/login/'})
        return HttpResponseRedirect('/login/')

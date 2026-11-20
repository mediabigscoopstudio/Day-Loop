"""Seller login (staff/customers denied), self-registration, and logout with confirmation."""
from django import forms
from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View

from sellers.models import SellerProfile
from sellers.validators import validate_phone
from ui.throttle import LoginThrottle

from .access import SellerRequiredMixin, get_seller

GENERIC_ERROR = 'Invalid credentials or not authorised'
THROTTLE_ERROR = 'Too many failed attempts. Please try again in a few minutes.'
login_throttle = LoginThrottle('seller-login-fail')
register_throttle = LoginThrottle('seller-register', max_attempts=10)


def safe_next(request, value):
    if value and value.startswith('/') and not value.startswith('//') and url_has_allowed_host_and_scheme(
            value, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return value
    return '/'


class LoginForm(forms.Form):
    identifier = forms.CharField(max_length=254, strip=True)
    password = forms.CharField(max_length=256, strip=False)


class LoginView(View):
    template = 'seller/login.html'

    def get(self, request):
        if get_seller(request.user):
            return HttpResponseRedirect(safe_next(request, request.GET.get('next')))
        return render(request, self.template, {'next': request.GET.get('next', '')})

    def post(self, request):
        form = LoginForm(request.POST)
        ctx = {'next': request.POST.get('next', '')}
        if not form.is_valid():
            return render(request, self.template, {**ctx, 'error': GENERIC_ERROR}, status=400)
        ident, password = form.cleaned_data['identifier'], form.cleaned_data['password']
        ctx['identifier'] = ident
        if login_throttle.is_throttled(request, ident):
            return render(request, self.template, {**ctx, 'error': THROTTLE_ERROR}, status=429)
        User = get_user_model()
        candidate = User.objects.filter(Q(username__iexact=ident) | Q(email__iexact=ident)).first()
        user = authenticate(request, username=candidate.get_username(), password=password) if candidate else None
        if candidate is None:
            User().set_password(password)            # similar timing whether or not the account exists
        if user is None or get_seller(user) is None:
            login_throttle.record_failure(request, ident)
            return render(request, self.template, {**ctx, 'error': GENERIC_ERROR}, status=400)
        login_throttle.clear(request, ident)
        login(request, user)
        return HttpResponseRedirect(safe_next(request, ctx['next']))


class RegisterForm(forms.Form):
    business_name = forms.CharField(max_length=160, label='Business / trade name')
    contact_person = forms.CharField(max_length=120, label='Your name')
    email = forms.EmailField()
    phone = forms.CharField(max_length=20)
    password1 = forms.CharField(strip=False, label='Password')
    password2 = forms.CharField(strip=False, label='Confirm password')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, f in self.fields.items():
            f.widget.attrs.setdefault('class', 'input')
        for name in ('password1', 'password2'):
            self.fields[name].widget = forms.PasswordInput(attrs={'class': 'input', 'autocomplete': 'new-password'})
        self.fields['email'].widget.attrs.update({'inputmode': 'email', 'autocomplete': 'email'})
        self.fields['phone'].widget.attrs.update({'inputmode': 'tel', 'autocomplete': 'tel'})

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        User = get_user_model()
        if User.objects.filter(Q(email__iexact=email) | Q(username__iexact=email)).exists():
            raise ValidationError('An account with this email already exists. Sign in instead.')
        return email

    def clean_phone(self):
        return validate_phone(self.cleaned_data['phone'])

    def clean(self):
        c = super().clean()
        if c.get('password1') and c.get('password1') != c.get('password2'):
            self.add_error('password2', 'The two passwords do not match.')
        elif c.get('password1'):
            try:
                validate_password(c['password1'])
            except ValidationError as e:
                self.add_error('password1', e)
        return c


class RegisterView(View):
    template = 'seller/register.html'

    def get(self, request):
        return render(request, self.template, {'form': RegisterForm()})

    def post(self, request):
        if register_throttle.is_throttled(request, 'register'):
            return render(request, self.template, {'form': RegisterForm(), 'error': THROTTLE_ERROR}, status=429)
        register_throttle.record_failure(request, 'register')       # counts every attempt per IP
        form = RegisterForm(request.POST)
        if not form.is_valid():
            return render(request, self.template, {'form': form}, status=422)
        d = form.cleaned_data
        User = get_user_model()
        with transaction.atomic():
            user = User.objects.create_user(
                username=d['email'], email=d['email'], password=d['password1'], first_name=d['contact_person'].split()[0][:150],
            )
            SellerProfile.objects.create(
                user=user, business_name=d['business_name'], contact_person=d['contact_person'],
                email=d['email'], phone=d['phone'], status=SellerProfile.Status.DRAFT,
            )
        login(request, user)
        return HttpResponseRedirect('/status/?welcome=1')


class LogoutConfirmView(SellerRequiredMixin, View):
    def get(self, request):
        return render(request, 'ui/confirm_modal.html', {
            'modal_size': 'sm', 'variant': 'warning', 'icon': 'logout', 'title': 'Sign out',
            'message': 'Sign out of the seller portal?', 'detail': 'Your drafts are saved.',
            'confirm_label': 'Sign out', 'post_url': '/logout/',
        })


class LogoutView(SellerRequiredMixin, View):
    def post(self, request):
        logout(request)
        if request.headers.get('HX-Request') == 'true':
            return HttpResponse(status=204, headers={'HX-Redirect': '/login/'})
        return HttpResponseRedirect('/login/')

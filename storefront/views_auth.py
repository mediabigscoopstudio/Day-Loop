from django.contrib.auth import authenticate, get_user_model, login, logout, update_session_auth_hash
from .common import StoreLoginRequired as LoginRequiredMixin
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import render
from django.views import View

from . import delivery
from .cart import merge_session_cart
from .common import confirm, done, next_url, popup
from .forms import LoginForm, PasswordForm, ProfileForm, ScheduleForm, SignupForm
from .models import NewsletterSignup

User = get_user_model()


def form_modal(request, form, *, title, post_url, submit='Save', subtitle='', size='sm', extra=None, status=200, switch=None):
    return popup(request, 'storefront/modals/form.html', {
        'form': form, 'title': title, 'post_url': post_url, 'submit': submit, 'subtitle': subtitle,
        'modal_size': size, 'extra': extra or {}, 'switch': switch}, status=status)


class LoginModalView(View):
    def get(self, request):
        return form_modal(request, LoginForm(), title='Sign in', post_url=request.path, submit='Sign in',
                          subtitle='Welcome back to dayloop.', extra={'next': request.GET.get('next', '')},
                          switch=('New here? Create an account', 'storefront:signup-modal'))

    def post(self, request):
        form = LoginForm(request.POST)
        extra = {'next': request.POST.get('next', '')}
        if form.is_valid():
            ident = form.cleaned_data['identifier']
            cand = User.objects.filter(Q(username__iexact=ident) | Q(email__iexact=ident)).first()
            user = authenticate(request, username=cand.get_username(), password=form.cleaned_data['password']) if cand else None
            if user and user.is_active:
                login(request, user)
                merge_session_cart(request, user)
                return done(request, f'Welcome back, {user.first_name or user.get_username()}!', redirect_to=next_url(request))
            form.add_error(None, 'Invalid email or password.')
        return form_modal(request, form, title='Sign in', post_url=request.path, submit='Sign in', extra=extra, status=422,
                          switch=('New here? Create an account', 'storefront:signup-modal'))


class SignupModalView(View):
    def get(self, request):
        return form_modal(request, SignupForm(), title='Create your account', post_url=request.path, submit='Sign up',
                          extra={'next': request.GET.get('next', '')}, switch=('Have an account? Sign in', 'storefront:login-modal'))

    def post(self, request):
        form = SignupForm(request.POST)
        if form.is_valid():
            d = form.cleaned_data
            parts = d['name'].split()
            user = User.objects.create_user(username=d['email'], email=d['email'], password=d['password'],
                                            first_name=parts[0], last_name=' '.join(parts[1:]))
            login(request, user, backend='django.contrib.auth.backends.ModelBackend')
            merge_session_cart(request, user)
            return done(request, 'Account created. Welcome to dayloop!', redirect_to=next_url(request))
        return form_modal(request, form, title='Create your account', post_url=request.path, submit='Sign up',
                          extra={'next': request.POST.get('next', '')}, status=422,
                          switch=('Have an account? Sign in', 'storefront:login-modal'))


class LogoutView(View):
    def get(self, request):
        return confirm(request, title='Log out', message='Log out of dayloop?', variant='warning', icon='logout',
                       consequence='Your cart stays saved to your account.', confirm_label='Log out', post_url=request.path)

    def post(self, request):
        logout(request)
        return done(request, 'You have been logged out.', redirect_to='/')


class ProfileModalView(LoginRequiredMixin, View):
    def get(self, request):
        u = request.user
        return form_modal(request, ProfileForm(initial={'first_name': u.first_name, 'last_name': u.last_name, 'email': u.email}),
                          title='Account details', post_url=request.path)

    def post(self, request):
        form = ProfileForm(request.POST)
        if form.is_valid():
            if User.objects.filter(email__iexact=form.cleaned_data['email']).exclude(pk=request.user.pk).exists():
                form.add_error('email', 'That email is already in use.')
            else:
                for k, v in form.cleaned_data.items():
                    setattr(request.user, k, v)
                request.user.save()
                return done(request, 'Account details saved.')
        return form_modal(request, form, title='Account details', post_url=request.path, status=422)


class PasswordModalView(LoginRequiredMixin, View):
    def get(self, request):
        return form_modal(request, PasswordForm(), title='Change password', post_url=request.path, submit='Update password')

    def post(self, request):
        form = PasswordForm(request.POST)
        if form.is_valid():
            if not request.user.check_password(form.cleaned_data['current']):
                form.add_error('current', 'Current password is wrong.')
            else:
                request.user.set_password(form.cleaned_data['new'])
                request.user.save()
                update_session_auth_hash(request, request.user)
                return done(request, 'Password updated.', refresh=False)
        return form_modal(request, form, title='Change password', post_url=request.path, submit='Update password', status=422)


class AreaModalView(View):
    """Address picker chip: area search + optional 'Use my location' (falls back to search)."""
    def get(self, request):
        q = request.GET.get('q', '')
        ctx = {'areas': delivery.search_areas(q), 'q': q, 'current': delivery.session_area(request)}
        if request.headers.get('HX-Target') == 'area-results':
            return render(request, 'storefront/partials/area_results.html', ctx)
        return popup(request, 'storefront/modals/area.html', ctx)

    def post(self, request):
        a = delivery.find_area(request.POST.get('area'), request.POST.get('city', ''))
        if not a:                                  # free-text area from geolocation: tier from city default
            area, city = request.POST.get('area', '').strip()[:80], request.POST.get('city', '').strip()[:80]
            if not area:
                return done(request, 'Choose an area.', 'error', refresh=False)
        else:
            area, city = a['area'], a['city']
        request.session['area'], request.session['city'] = area, city
        return done(request, f'Delivering to {area}.')


class ScheduleModalView(View):
    def get(self, request):
        return form_modal(request, ScheduleForm(), title='Schedule your delivery', post_url=request.path, submit='Confirm slot')

    def post(self, request):
        form = ScheduleForm(request.POST)
        if form.is_valid():
            request.session['schedule'] = {'date': form.cleaned_data['date'].isoformat(), 'slot': form.cleaned_data['slot']}
            request.session['speed'] = 'scheduled'
            return done(request, 'Delivery slot saved.')
        return form_modal(request, form, title='Schedule your delivery', post_url=request.path, submit='Confirm slot', status=422)


class SpeedView(View):
    def post(self, request):
        tier = delivery.session_tier(request)
        key = request.POST.get('speed', '')
        opt = next((o for o in delivery.options_for(tier) if o['key'] == key), None)
        if not opt or not opt['available']:
            return done(request, 'That speed is not available in your area.', 'error', refresh=False)
        request.session['speed'] = key
        return done(request, f'{opt["label"]} selected.')


class NewsletterView(View):
    def post(self, request):
        email = request.POST.get('email', '').strip().lower()
        from django.core.exceptions import ValidationError
        from django.core.validators import validate_email
        try:
            validate_email(email)
        except ValidationError:
            resp = HttpResponse(status=422)
            resp['HX-Trigger'] = '{"toast": {"message": "Enter a valid email address.", "level": "error"}}'
            return resp
        NewsletterSignup.objects.get_or_create(email=email)
        resp = HttpResponse(status=204)
        resp['HX-Trigger'] = '{"toast": {"message": "Thanks! You are on the list.", "level": "success"}}'
        return resp

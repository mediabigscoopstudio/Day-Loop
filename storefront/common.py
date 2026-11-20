import json

from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse

from . import delivery
from .cart import get_cart


def is_htmx(request):
    return request.headers.get('HX-Request') == 'true'


def page_ctx(request, **extra):
    ctx = {'cart': get_cart(request)}
    ctx.update(extra)
    return ctx


def popup(request, template, ctx=None, status=200):
    """Popups are fragments. A direct (non-HTMX) visit goes home instead of showing a bare fragment."""
    if not is_htmx(request):
        return redirect('storefront:home')
    return render(request, template, ctx or {}, status=status)


def confirm(request, *, title, message, post_url, consequence='', confirm_label='Confirm',
            variant='danger', icon='trash', extra=None, detail=''):
    return popup(request, 'ui/confirm_modal.html', {
        'modal_size': 'sm', 'title': title, 'message': message, 'consequence': consequence, 'detail': detail,
        'confirm_label': confirm_label, 'variant': variant, 'icon': icon, 'post_url': post_url, 'extra': extra or {},
    })


def done(request, message='', level='success', redirect_to=None, refresh=True):
    """Close the popup, flash a toast (shown after navigation) and refresh or go to a URL."""
    if message:
        (messages.success if level == 'success' else messages.error)(request, message)
    resp = HttpResponse(status=204)
    if redirect_to:
        resp['HX-Redirect'] = redirect_to
    elif refresh:
        resp['HX-Refresh'] = 'true'
    else:
        resp['HX-Trigger'] = json.dumps({'toast': {'message': message, 'level': level}, 'closeModal': True})
    return resp


def toast_trigger(resp, message, level='success'):
    resp['HX-Trigger'] = json.dumps({'toast': {'message': message, 'level': level}})
    return resp


def next_url(request, default=None):
    from django.utils.http import url_has_allowed_host_and_scheme
    n = request.POST.get('next') or request.GET.get('next') or ''
    ok = n.startswith('/') and not n.startswith('//') and url_has_allowed_host_and_scheme(n, {request.get_host()})
    return n if ok else (default or reverse('storefront:home'))


class StoreLoginRequired:
    """Anonymous: HTMX gets the login popup, full pages go home and open it."""
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            url = reverse('storefront:login-modal')
            nxt = request.get_full_path()
            if is_htmx(request):
                return redirect(f'{url}?next={nxt}')
            return redirect(f"{reverse('storefront:home')}?login=1&next={nxt}")
        return super().dispatch(request, *args, **kwargs)

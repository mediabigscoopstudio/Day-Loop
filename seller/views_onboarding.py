"""Onboarding wizard as a 4-step popup. Each step saves a draft; the seller can close and resume."""
from django.http import HttpResponse
from django.shortcuts import render
from django.views import View

from sellers.models import SellerDocument

from .access import SellerRequiredMixin
from .forms_onboarding import BankOpsForm, BusinessForm, ComplianceForm, ReviewForm
from .services import onboarding as svc

STEPS = [(1, 'Business'), (2, 'Compliance'), (3, 'Bank & operations'), (4, 'Review')]


def _initial_compliance(s):
    return dict(gst_number=s.gst_number, pan_number=s.pan_number, company_pan=s.company_pan, fssai_number=s.fssai_number,
                fssai_expiry=s.fssai_expiry, mfg_licence_number=s.mfg_licence_number)


def _initial_bank(s):
    initial = dict(dispatch_days=s.dispatch_days, dispatch_address=s.dispatch_address, categories=list(s.categories.all()))
    if hasattr(s, 'bank'):
        b = s.bank
        initial.update(account_holder=b.account_holder, ifsc=b.ifsc, bank_name=b.bank_name, upi_id=b.upi_id)
    return initial


def _build_form(step, seller, data=None, files=None):
    if step == 1:
        return BusinessForm(data, files, instance=seller)
    if step == 2:
        return ComplianceForm(data, files, seller=seller, initial=_initial_compliance(seller))
    if step == 3:
        return BankOpsForm(data, files, seller=seller, initial=_initial_bank(seller))
    return ReviewForm(data)


def _clamp(seller, step):
    try:
        step = int(step)
    except (TypeError, ValueError):
        step = seller.onboarding_step
    return max(1, min(step, seller.onboarding_step, 4))


def _render(request, seller, step, form, status=200, **extra):
    docs = {d.kind: d for d in seller.documents.all()}
    ctx = dict(
        seller=seller, step=step, form=form, modal_size='lg', docs=docs, steps=[
            (n, label, 'done' if n < step else ('current' if n == step else 'todo')) for n, label in STEPS],
        missing=svc.missing_items(seller) if step == 4 else [], K=SellerDocument.Kind,
        bank=getattr(seller, 'bank', None) if hasattr(seller, 'bank') else None, **extra)
    return render(request, 'seller/onboarding/wizard.html', ctx, status=status)


class OnboardingView(SellerRequiredMixin, View):
    def get(self, request):
        s = self.seller
        if not svc.is_editable(s):
            return render(request, 'seller/onboarding/locked.html', {'seller': s, 'modal_size': 'sm'})
        step = _clamp(s, request.GET.get('step'))
        return _render(request, s, step, _build_form(step, s))


class OnboardingStepView(SellerRequiredMixin, View):
    def post(self, request, step):
        s = self.seller
        if not svc.is_editable(s):
            return render(request, 'seller/onboarding/locked.html', {'seller': s, 'modal_size': 'sm'}, status=403)
        step = _clamp(s, step)
        if step == 4:
            return HttpResponse(status=400)
        form = _build_form(step, s, request.POST, request.FILES)
        if not form.is_valid():
            return _render(request, s, step, form, status=422)
        {1: svc.save_business, 2: svc.save_compliance, 3: svc.save_bank_ops}[step](s, form)
        s.refresh_from_db()
        nxt = min(step + 1, 4)
        return _render(request, s, nxt, _build_form(nxt, s), saved=step)


class OnboardingSubmitView(SellerRequiredMixin, View):
    def post(self, request):
        s = self.seller
        form = ReviewForm(request.POST)
        if not form.is_valid():
            return _render(request, s, 4, form, status=422)
        try:
            svc.submit(s.pk, request.user)
        except svc.OnboardingError as e:
            return _render(request, s, 4, form, status=422, form_error=str(e))
        import json
        return HttpResponse(status=204, headers={
            'HX-Redirect': '/status/',
            'HX-Trigger': json.dumps({'toast': {'message': 'Application submitted for review.', 'level': 'success'}}),
        })


class InfoReplyView(SellerRequiredMixin, View):
    def _ctx(self, seller, **extra):
        last = seller.history.filter(to_status='needs_info').first()
        return {'seller': seller, 'request_text': last.reason if last else '', 'modal_size': 'md', **extra}

    def get(self, request):
        return render(request, 'seller/onboarding/reply_modal.html', self._ctx(self.seller))

    def post(self, request):
        message = request.POST.get('message', '')
        try:
            svc.reply_to_request(self.seller.pk, message, request.user)
        except svc.OnboardingError as e:
            return render(request, 'seller/onboarding/reply_modal.html',
                          self._ctx(self.seller, error=str(e), message=message), status=422)
        import json
        return HttpResponse(status=204, headers={
            'HX-Redirect': '/status/',
            'HX-Trigger': json.dumps({'toast': {'message': 'Reply sent. Your application is back under review.', 'level': 'success'}}),
        })

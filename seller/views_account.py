"""Account: profile + logo, business and compliance details, bank (re-verification), password, documents."""
from datetime import date, timedelta

from django.contrib.auth import update_session_auth_hash
from django.shortcuts import render
from django.views import View

from catalog.models import EXPIRY_WARN_DAYS
from sellers.models import SellerBank, SellerDocument

from .access import ApprovedSellerMixin, SellerRequiredMixin
from .base import SellerPageView
from .forms_account import BankEditForm, DocumentReplaceForm, PasswordChangeForm, ProfileForm
from .services.onboarding import _replace_document
from .views_variants import trigger

EVENT = ('account-changed',)


def expiry_state(d):
    if not d:
        return None
    left = (d - date.today()).days
    return 'expired' if left < 0 else ('soon' if left <= EXPIRY_WARN_DAYS else 'ok')


class AccountView(SellerPageView):
    template_name = 'seller/account.html'
    active = 'account'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        s = self.seller
        docs = [(d, expiry_state(d.expires_on)) for d in s.documents.all()]
        warnings = [f'{d.get_kind_display()} {"has expired" if st == "expired" else "expires soon"} ({d.expires_on:%b %-d, %Y})'
                    for d, st in docs if st in ('expired', 'soon')]
        fs = expiry_state(s.fssai_expiry)
        if fs in ('expired', 'soon') and not any('FSSAI' in w for w in warnings):
            warnings.append(f'FSSAI licence {"has expired" if fs == "expired" else "expires soon"} ({s.fssai_expiry:%b %-d, %Y})')
        ctx.update(bank=getattr(s, 'bank', None) if hasattr(s, 'bank') else None, docs=docs, warnings=warnings,
                   categories=s.categories.all(), fssai_state=fs, can_edit=s.is_approved)
        return ctx


class ProfileEditView(ApprovedSellerMixin, View):
    def _render(self, request, form, status=200):
        return render(request, 'seller/account/profile_modal.html', {'form': form, 'seller': self.seller, 'modal_size': 'md', 'sheet': True}, status=status)

    def get(self, request):
        return self._render(request, ProfileForm(instance=self.seller))

    def post(self, request):
        form = ProfileForm(request.POST, request.FILES, instance=self.seller)
        if not form.is_valid():
            return self._render(request, form, 422)
        form.save()
        return trigger('Profile updated.', events=EVENT)


class BankEditView(ApprovedSellerMixin, View):
    def _bank(self):
        return self.seller.bank if hasattr(self.seller, 'bank') else None

    def _render(self, request, form, status=200):
        return render(request, 'seller/account/bank_modal.html', {'form': form, 'bank': self._bank(), 'modal_size': 'md', 'sheet': True}, status=status)

    def get(self, request):
        b = self._bank()
        initial = dict(account_holder=b.account_holder, ifsc=b.ifsc, bank_name=b.bank_name, upi_id=b.upi_id) if b else {}
        return self._render(request, BankEditForm(initial=initial, user=request.user, bank=b))

    def post(self, request):
        b = self._bank()
        form = BankEditForm(request.POST, user=request.user, bank=b)
        if not form.is_valid():
            return self._render(request, form, 422)
        d = form.cleaned_data
        if b is None:
            SellerBank.objects.create(seller=self.seller, account_holder=d['account_holder'], account_number=d['account_number'],
                                      ifsc=d['ifsc'], bank_name=d['bank_name'], upi_id=d['upi_id'])
            changed = True
        else:
            changed = (bool(d['account_number']) and d['account_number'] != b.account_number) or d['ifsc'] != b.ifsc \
                or d['account_holder'] != b.account_holder
            b.account_holder, b.ifsc, b.bank_name, b.upi_id = d['account_holder'], d['ifsc'], d['bank_name'], d['upi_id']
            if d['account_number']:
                b.account_number = d['account_number']
            if changed:
                b.verified = False                          # payouts to changed details wait for re-verification
            b.save()
        msg = 'Bank details saved. They will be re-verified before your next payout.' if changed else 'Bank details saved.'
        return trigger(msg, events=EVENT)


class PasswordView(SellerRequiredMixin, View):
    def _render(self, request, form, status=200):
        return render(request, 'seller/account/password_modal.html', {'form': form, 'modal_size': 'sm', 'sheet': True}, status=status)

    def get(self, request):
        return self._render(request, PasswordChangeForm(user=request.user))

    def post(self, request):
        form = PasswordChangeForm(request.POST, user=request.user)
        if not form.is_valid():
            return self._render(request, form, 422)
        request.user.set_password(form.cleaned_data['new_password'])
        request.user.save(update_fields=['password'])
        update_session_auth_hash(request, request.user)     # keep this session signed in, end any others
        return trigger('Password changed.', events=())


class DocumentReplaceView(ApprovedSellerMixin, View):
    def _render(self, request, form, status=200):
        return render(request, 'seller/account/document_modal.html', {'form': form, 'modal_size': 'md', 'sheet': True}, status=status)

    def get(self, request):
        kind = request.GET.get('kind')
        return self._render(request, DocumentReplaceForm(initial={'kind': kind} if kind else {}))

    def post(self, request):
        form = DocumentReplaceForm(request.POST, request.FILES)
        if not form.is_valid():
            return self._render(request, form, 422)
        d = form.cleaned_data
        _replace_document(self.seller, d['kind'], d['file'], expires_on=d['expires_on'])
        if d['kind'] == SellerDocument.Kind.FSSAI and d['expires_on']:
            self.seller.fssai_expiry = d['expires_on']
            self.seller.save(update_fields=['fssai_expiry'])
        return trigger('Document updated.', events=EVENT)

"""Saving onboarding steps, completeness checks, submission and the needs-info reply."""
from django.db import transaction
from django.utils import timezone

from sellers.models import SellerBank, SellerDocument, SellerInfoReply, SellerProfile, SellerStatusHistory

from ..forms_onboarding import DOC_FIELDS

S = SellerProfile.Status
EDITABLE = {S.DRAFT, S.NEEDS_INFO}      # statuses in which the wizard can be edited
REQUIRED_DOC_KINDS = {SellerDocument.Kind.GST, SellerDocument.Kind.PAN, SellerDocument.Kind.FSSAI}


class OnboardingError(Exception):
    """Safe-to-show message."""


def is_editable(seller):
    return seller.status in EDITABLE


def _advance(seller, step):
    seller.onboarding_step = max(seller.onboarding_step, min(step + 1, 4))
    seller.save(update_fields=['onboarding_step'])


def _replace_document(seller, kind, file, expires_on=None):
    for old in seller.documents.filter(kind=kind):
        old.file.delete(save=False)
        old.delete()
    return SellerDocument.objects.create(seller=seller, kind=kind, file=file, expires_on=expires_on)


@transaction.atomic
def save_business(seller, form):
    obj = form.save(commit=False)
    obj.onboarding_step = max(seller.onboarding_step, 2)
    obj.save()
    return obj


@transaction.atomic
def save_compliance(seller, form):
    d = form.cleaned_data
    if d['gst_number'] != seller.gst_number:
        seller.gst_status = SellerProfile.GstCheck.UNVERIFIED        # admin re-verifies a changed GSTIN
    seller.gst_number, seller.pan_number, seller.company_pan = d['gst_number'], d['pan_number'], d['company_pan']
    seller.fssai_number, seller.fssai_expiry = d['fssai_number'], d['fssai_expiry']
    seller.mfg_licence_number = d['mfg_licence_number']
    seller.save()
    for name, kind, _ in DOC_FIELDS:
        f = form.picked_file(name)
        if f:
            _replace_document(seller, kind, f, expires_on=d['fssai_expiry'] if kind == SellerDocument.Kind.FSSAI else None)
    _advance(seller, 2)
    return seller


@transaction.atomic
def save_bank_ops(seller, form):
    d = form.cleaned_data
    bank, created = SellerBank.objects.get_or_create(seller=seller, defaults=dict(
        account_holder=d['account_holder'], account_number=d['account_number'], ifsc=d['ifsc'], bank_name=d['bank_name'],
        upi_id=d['upi_id']))
    if not created:
        changed = (d['account_number'] and d['account_number'] != bank.account_number) or d['ifsc'] != bank.ifsc
        bank.account_holder, bank.ifsc, bank.bank_name, bank.upi_id = d['account_holder'], d['ifsc'], d['bank_name'], d['upi_id']
        if d['account_number']:
            bank.account_number = d['account_number']
        if changed:
            bank.verified = False              # new bank details need re-verification
        bank.save()
    cats = list(d['categories'])
    seller.categories.set(cats)
    seller.category = cats[0] if cats else None
    seller.dispatch_days, seller.dispatch_address = d['dispatch_days'], d['dispatch_address']
    seller.save()
    cheque = form.picked_file('doc_cheque')
    if cheque:
        _replace_document(seller, SellerDocument.Kind.CHEQUE, cheque)
    _advance(seller, 3)
    return seller


def missing_items(seller):
    """What still blocks submission, as short human labels."""
    missing = []
    for label, value in (('Legal name', seller.legal_name), ('Trade name', seller.business_name), ('Business type', seller.business_type),
                         ('Contact person', seller.contact_person), ('Phone', seller.phone), ('Email', seller.email),
                         ('Registered address', seller.address)):
        if not value:
            missing.append(label)
    for label, value in (('GST number', seller.gst_number), ('PAN', seller.pan_number), ('FSSAI number', seller.fssai_number),
                         ('FSSAI expiry', seller.fssai_expiry)):
        if not value:
            missing.append(label)
    have = set(seller.documents.values_list('kind', flat=True))
    for kind in REQUIRED_DOC_KINDS:
        if kind not in have:
            missing.append(f'{SellerDocument.Kind(kind).label} (upload)')
    if not hasattr(seller, 'bank'):
        missing.append('Bank details')
    if not seller.categories.exists():
        missing.append('Product categories')
    return missing


@transaction.atomic
def submit(seller_id, actor):
    seller = SellerProfile.objects.select_for_update().get(pk=seller_id)
    if seller.status not in EDITABLE:
        raise OnboardingError('This application can no longer be edited.')
    missing = missing_items(seller)
    if missing:
        raise OnboardingError('Please complete: ' + ', '.join(missing) + '.')
    now = timezone.now()
    SellerStatusHistory.objects.create(
        seller=seller, from_status=seller.status, to_status=S.PENDING, actor=actor,
        reason='Application submitted' if seller.status == S.DRAFT else 'Application re-submitted',
    )
    seller.status, seller.submitted_at, seller.commission_accepted_at, seller.onboarding_step = S.PENDING, now, now, 4
    seller.save(update_fields=['status', 'submitted_at', 'commission_accepted_at', 'onboarding_step'])
    return seller


@transaction.atomic
def reply_to_request(seller_id, message, actor):
    seller = SellerProfile.objects.select_for_update().get(pk=seller_id)
    message = (message or '').strip()
    if seller.status != S.NEEDS_INFO:
        raise OnboardingError('There is no open request to reply to.')
    if not message:
        raise OnboardingError('Please write your reply.')
    SellerInfoReply.objects.create(seller=seller, message=message)
    SellerStatusHistory.objects.create(
        seller=seller, from_status=S.NEEDS_INFO, to_status=S.PENDING, actor=actor, reason=f'Seller replied: {message}')
    seller.status, seller.submitted_at = S.PENDING, timezone.now()
    seller.save(update_fields=['status', 'submitted_at'])
    return seller

from django.conf import settings
from django.db import models

from .validators import mask_account


def logo_path(instance, filename):
    return f'sellers/{instance.pk or "new"}/logo/{filename}'


def document_path(instance, filename):
    return f'sellers/{instance.seller_id}/docs/{instance.kind}/{filename}'


class SellerProfile(models.Model):
    class Status(models.TextChoices):
        DRAFT = 'draft', 'Draft'                 # onboarding not submitted yet
        PENDING = 'pending', 'Pending'           # submitted, under review
        APPROVED = 'approved', 'Approved'
        REJECTED = 'rejected', 'Rejected'
        NEEDS_INFO = 'needs_info', 'Needs info'

    class BusinessType(models.TextChoices):
        MANUFACTURER = 'manufacturer', 'Manufacturer'
        WHOLESALER = 'wholesaler', 'Wholesaler'
        BRAND_OWNER = 'brand_owner', 'Brand owner'

    class GstCheck(models.TextChoices):
        UNVERIFIED = 'unverified', 'Not verified'
        VERIFIED = 'verified', 'Verified'
        FAILED = 'failed', 'Verification failed'

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='seller_profile'
    )
    code = models.CharField(max_length=8, unique=True, null=True, blank=True, help_text='Short code used in invoice numbers')
    invoice_seq = models.PositiveIntegerField(default=0)

    # Step 1: business
    business_name = models.CharField('Trade name', max_length=160)
    legal_name = models.CharField(max_length=200, blank=True)
    business_type = models.CharField(max_length=14, choices=BusinessType.choices, blank=True)
    logo = models.ImageField(upload_to=logo_path, blank=True)
    contact_person = models.CharField(max_length=120, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField('Registered address', blank=True)
    city = models.CharField(max_length=80, blank=True)
    year_established = models.PositiveSmallIntegerField(null=True, blank=True)

    # Step 2: compliance
    gst_number = models.CharField('GST number', max_length=20, blank=True)
    gst_status = models.CharField(max_length=10, choices=GstCheck.choices, default=GstCheck.UNVERIFIED)
    pan_number = models.CharField('PAN', max_length=12, blank=True)
    company_pan = models.CharField(max_length=12, blank=True)
    fssai_number = models.CharField('FSSAI number', max_length=20, blank=True)
    fssai_expiry = models.DateField(null=True, blank=True)
    mfg_licence_number = models.CharField(max_length=60, blank=True)
    # legacy URL fields kept for the admin dashboard
    gst_document_url = models.URLField(blank=True)
    fssai_document_url = models.URLField(blank=True)
    other_document_url = models.URLField(blank=True)

    # Step 3: operations
    category = models.ForeignKey(
        'catalog.Category', null=True, blank=True, on_delete=models.SET_NULL, related_name='+'
    )
    categories = models.ManyToManyField('catalog.Category', blank=True, related_name='sellers_selling')
    dispatch_days = models.PositiveSmallIntegerField(default=2)
    dispatch_address = models.TextField(blank=True)

    # Step 4 + workflow
    onboarding_step = models.PositiveSmallIntegerField(default=1)
    commission_accepted_at = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT)
    applied_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-applied_at']
        indexes = [models.Index(fields=['status', 'applied_at'])]

    def __str__(self):
        return self.business_name

    @property
    def is_approved(self):
        return self.status == self.Status.APPROVED

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = self._make_code()
        super().save(*args, **kwargs)

    def _make_code(self):
        base = ''.join(c for c in (self.business_name or 'SLR').upper() if c.isalnum())[:4] or 'SLR'
        code, n = base, 1
        while SellerProfile.objects.filter(code=code).exists():
            n += 1
            code = f'{base[:5]}{n}'
        return code


class SellerBank(models.Model):
    seller = models.OneToOneField(SellerProfile, on_delete=models.CASCADE, related_name='bank')
    account_holder = models.CharField(max_length=120)
    account_number = models.CharField(max_length=24)
    ifsc = models.CharField('IFSC', max_length=11)
    bank_name = models.CharField(max_length=80)
    upi_id = models.CharField('UPI ID', max_length=80, blank=True)
    verified = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def masked_number(self):
        return mask_account(self.account_number)


class SellerDocument(models.Model):
    class Kind(models.TextChoices):
        GST = 'gst', 'GST certificate'
        PAN = 'pan', 'PAN card'
        COMPANY_PAN = 'company_pan', 'Company PAN'
        FSSAI = 'fssai', 'FSSAI licence'
        MFG = 'mfg_licence', 'Manufacturing licence'
        GMP = 'gmp', 'GMP certificate'
        ISO = 'iso22000', 'ISO 22000 certificate'
        HACCP = 'haccp', 'HACCP certificate'
        CHEQUE = 'cheque', 'Cancelled cheque'
        OTHER = 'other', 'Other'

    seller = models.ForeignKey(SellerProfile, on_delete=models.CASCADE, related_name='documents')
    kind = models.CharField(max_length=14, choices=Kind.choices)
    file = models.FileField(upload_to=document_path)
    expires_on = models.DateField(null=True, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['kind', '-uploaded_at']


class SellerStatusHistory(models.Model):
    """Every approve / reject / request-info decision: who, when, why."""

    seller = models.ForeignKey(SellerProfile, on_delete=models.CASCADE, related_name='history')
    from_status = models.CharField(max_length=12, choices=SellerProfile.Status.choices)
    to_status = models.CharField(max_length=12, choices=SellerProfile.Status.choices)
    reason = models.TextField(blank=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name_plural = 'seller status history'


class SellerInfoReply(models.Model):
    """The seller's answer to an admin 'needs info' request."""

    seller = models.ForeignKey(SellerProfile, on_delete=models.CASCADE, related_name='info_replies')
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

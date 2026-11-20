from django.conf import settings
from django.db import models


class SellerProfile(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        APPROVED = 'approved', 'Approved'
        REJECTED = 'rejected', 'Rejected'
        NEEDS_INFO = 'needs_info', 'Needs info'

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='seller_profile'
    )
    business_name = models.CharField(max_length=160)
    category = models.ForeignKey(
        'catalog.Category', null=True, blank=True, on_delete=models.SET_NULL, related_name='+'
    )
    phone = models.CharField(max_length=20, blank=True)
    city = models.CharField(max_length=80, blank=True)
    gst_number = models.CharField('GST number', max_length=20, blank=True)
    fssai_number = models.CharField('FSSAI number', max_length=20, blank=True)
    gst_document_url = models.URLField(blank=True)
    fssai_document_url = models.URLField(blank=True)
    other_document_url = models.URLField(blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    applied_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-applied_at']
        indexes = [models.Index(fields=['status', 'applied_at'])]

    def __str__(self):
        return self.business_name


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

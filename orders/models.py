from decimal import Decimal

from django.conf import settings
from django.db import models


class Order(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        PROCESSING = 'processing', 'Processing'
        SHIPPED = 'shipped', 'Shipped'
        DELIVERED = 'delivered', 'Delivered'
        CANCELLED = 'cancelled', 'Cancelled'

    class PaymentStatus(models.TextChoices):
        PENDING = 'pending', 'Pending'
        PAID = 'paid', 'Paid'
        FAILED = 'failed', 'Failed'
        REFUNDED = 'refunded', 'Refunded'

    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='orders'
    )
    number = models.CharField(max_length=20, unique=True, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    payment_status = models.CharField(
        max_length=10, choices=PaymentStatus.choices, default=PaymentStatus.PENDING
    )
    payment_method = models.CharField(max_length=30, blank=True)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0'))
    ship_name = models.CharField(max_length=120, blank=True)
    ship_line1 = models.CharField(max_length=200, blank=True)
    ship_city = models.CharField(max_length=80, blank=True)
    ship_state = models.CharField(max_length=80, blank=True)
    ship_pincode = models.CharField(max_length=10, blank=True)
    placed_at = models.DateTimeField(db_index=True)

    class Meta:
        ordering = ['-placed_at']
        indexes = [models.Index(fields=['status', 'placed_at'])]

    def __str__(self):
        return self.number or f'Order {self.pk}'

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.number:
            self.number = f'DL-{100000 + self.pk}'
            super().save(update_fields=['number'])


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(
        'catalog.Product', on_delete=models.PROTECT, related_name='order_items'
    )
    # Denormalised from product.seller so per-seller sub-orders and seller
    # revenue are plain aggregations.
    seller = models.ForeignKey(
        'sellers.SellerProfile', on_delete=models.PROTECT, related_name='order_items'
    )
    seller_order = models.ForeignKey(
        'orders.SellerOrder', null=True, blank=True, on_delete=models.CASCADE, related_name='items'
    )
    variant = models.ForeignKey(
        'catalog.ProductVariant', null=True, blank=True, on_delete=models.PROTECT, related_name='order_items'
    )
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    gst_rate = models.PositiveSmallIntegerField(default=0)
    gst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0'))
    line_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0'))

    def save(self, *args, **kwargs):
        if self.variant_id and not self.product_id:
            self.product_id = self.variant.product_id
        if not self.seller_id:
            self.seller_id = self.product.seller_id
        self.line_total = self.unit_price * self.quantity
        super().save(*args, **kwargs)


class SellerOrder(models.Model):
    """One seller's share of a customer's checkout. Never mixes items from other sellers."""

    class Status(models.TextChoices):
        NEW = 'new', 'New'
        ACCEPTED = 'accepted', 'Accepted'
        PACKED = 'packed', 'Packed'
        SHIPPED = 'shipped', 'Shipped'
        DELIVERED = 'delivered', 'Delivered'
        CANCELLED = 'cancelled', 'Cancelled'
        RETURNED = 'returned', 'Returned'

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='seller_orders')
    seller = models.ForeignKey('sellers.SellerProfile', on_delete=models.PROTECT, related_name='seller_orders')
    invoice_number = models.CharField(max_length=40, unique=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.NEW, db_index=True)
    accept_by = models.DateTimeField(null=True, blank=True)
    shipment_index = models.PositiveSmallIntegerField(default=1)
    shipment_count = models.PositiveSmallIntegerField(default=1)

    # Money snapshot: later rate changes never touch old orders.
    purchase_value = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0'))
    commission_rate = models.DecimalField(max_digits=5, decimal_places=4, default=Decimal('0.0500'))
    gst_rate_on_margin = models.DecimalField(max_digits=5, decimal_places=4, default=Decimal('0.1800'))
    margin = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0'))
    margin_gst = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0'))
    payout = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0'))

    # Package and shipment
    package_weight_kg = models.DecimalField(max_digits=8, decimal_places=3, default=Decimal('0'))
    courier = models.CharField(max_length=60, blank=True)
    awb = models.CharField('AWB / tracking number', max_length=60, blank=True)
    tracking_url = models.URLField(blank=True)
    shipped_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']
        indexes = [models.Index(fields=['seller', 'status']), models.Index(fields=['seller', 'created_at'])]

    def __str__(self):
        return self.invoice_number


class SellerOrderEvent(models.Model):
    """Timeline entry written on every status change."""

    seller_order = models.ForeignKey(SellerOrder, on_delete=models.CASCADE, related_name='events')
    status = models.CharField(max_length=10, choices=SellerOrder.Status.choices)
    note = models.CharField(max_length=240, blank=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at', 'id']


class Payout(models.Model):
    """A settlement batch paid to a seller (created by the admin side)."""

    seller = models.ForeignKey('sellers.SellerProfile', on_delete=models.PROTECT, related_name='payouts')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    reference = models.CharField(max_length=60, blank=True)
    settled_at = models.DateTimeField()
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')

    class Meta:
        ordering = ['-settled_at']


class LedgerEntry(models.Model):
    """Per-SellerOrder money movement: credit on delivery, debit on refund/return."""

    class Kind(models.TextChoices):
        CREDIT = 'credit', 'Credit'
        DEBIT = 'debit', 'Debit'

    seller = models.ForeignKey('sellers.SellerProfile', on_delete=models.PROTECT, related_name='ledger')
    seller_order = models.ForeignKey(SellerOrder, null=True, blank=True, on_delete=models.PROTECT, related_name='ledger')
    kind = models.CharField(max_length=6, choices=Kind.choices)
    amount = models.DecimalField(max_digits=12, decimal_places=2, help_text='Always positive; kind gives the sign')
    description = models.CharField(max_length=160, blank=True)
    payout = models.ForeignKey(Payout, null=True, blank=True, on_delete=models.SET_NULL, related_name='entries')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']
        indexes = [models.Index(fields=['seller', 'payout'])]

    @property
    def signed_amount(self):
        return self.amount if self.kind == self.Kind.CREDIT else -self.amount

    @property
    def is_settled(self):
        return self.payout_id is not None

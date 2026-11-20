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
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    line_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0'))

    def save(self, *args, **kwargs):
        if not self.seller_id:
            self.seller_id = self.product.seller_id
        self.line_total = self.unit_price * self.quantity
        super().save(*args, **kwargs)

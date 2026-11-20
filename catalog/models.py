from django.core.exceptions import ValidationError
from decimal import Decimal

from django.db import models
from django.utils.text import slugify


class Category(models.Model):
    """
    Two-level taxonomy in one self-referencing table.

    - Category    = row with parent IS NULL
    - SubCategory = row whose parent is a Category (max depth 2)
    """

    name = models.CharField(max_length=80)
    slug = models.SlugField(max_length=100, unique=True, blank=True)
    parent = models.ForeignKey(
        'self', null=True, blank=True, on_delete=models.PROTECT, related_name='children'
    )
    image = models.ImageField(upload_to='categories/', blank=True)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)
    default_gst_rate = models.PositiveSmallIntegerField(default=18, choices=[(0, '0%'), (5, '5%'), (12, '12%'), (18, '18%')])
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['sort_order', 'name']
        verbose_name_plural = 'categories'
        constraints = [
            models.UniqueConstraint(
                fields=['parent', 'name'], name='uniq_category_name_per_parent'
            ),
        ]

    def __str__(self):
        return f'{self.parent.name} / {self.name}' if self.parent_id else self.name

    @property
    def is_subcategory(self):
        return self.parent_id is not None

    def clean(self):
        super().clean()
        if self.parent_id:
            if self.pk and self.parent_id == self.pk:
                raise ValidationError({'parent': 'A category cannot be its own parent.'})
            if self.parent.parent_id:
                raise ValidationError(
                    {'parent': 'Categories can only be two levels deep (category, subcategory).'}
                )
            if self.pk and self.children.exists():
                raise ValidationError(
                    {'parent': 'This category has subcategories, so it cannot become a subcategory.'}
                )

    def _unique_slug(self):
        base = slugify(self.name) or 'category'
        slug, n = base, 2
        qs = Category.objects.exclude(pk=self.pk)
        while qs.filter(slug=slug).exists():
            slug = f'{base}-{n}'
            n += 1
        return slug

    def save(self, *args, **kwargs):
        self.full_clean_depth()
        if not self.slug:
            self.slug = self._unique_slug()
        super().save(*args, **kwargs)

    def full_clean_depth(self):
        """Depth rule is enforced on every save, not only in forms."""
        if self.parent_id and self.parent.parent_id:
            raise ValidationError('Categories can only be two levels deep.')

    def product_count(self):
        if self.parent_id:
            return self.products.count()
        return Product.objects.filter(subcategory__parent=self).count()


class Product(models.Model):
    class Status(models.TextChoices):
        DRAFT = 'draft', 'Draft'
        PENDING = 'pending', 'Pending review'
        LIVE = 'live', 'Live'
        REJECTED = 'rejected', 'Rejected'
        INACTIVE = 'inactive', 'Inactive'

    seller = models.ForeignKey('sellers.SellerProfile', on_delete=models.CASCADE, related_name='products')
    subcategory = models.ForeignKey(
        Category, on_delete=models.PROTECT, related_name='products',
        limit_choices_to={'parent__isnull': False},
    )
    name = models.CharField(max_length=160)
    slug = models.SlugField(max_length=180, unique=True, null=True, blank=True)
    brand = models.CharField(max_length=80, blank=True)
    short_description = models.CharField(max_length=220, blank=True)
    description = models.TextField(blank=True)
    thumbnail = models.ImageField(upload_to='products/thumbs/', blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT, db_index=True)
    rejection_reason = models.TextField(blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    meta_title = models.CharField(max_length=70, blank=True)
    meta_description = models.CharField(max_length=170, blank=True)
    meta_keywords = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['status', 'created_at']), models.Index(fields=['brand'])]

    def __str__(self):
        return self.name

    @property
    def category(self):
        return self.subcategory.parent

    @property
    def is_live(self):
        return self.status == self.Status.LIVE

    def clean(self):
        super().clean()
        if self.subcategory_id and not self.subcategory.parent_id:
            raise ValidationError({'subcategory': 'Choose a subcategory, not a top-level category.'})

    def _unique_slug(self):
        base = slugify(self.name)[:150] or 'product'
        slug, n = base, 2
        qs = Product.objects.exclude(pk=self.pk)
        while qs.filter(slug=slug).exists():
            slug = f'{base}-{n}'
            n += 1
        return slug

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = self._unique_slug()
        super().save(*args, **kwargs)


GST_RATES = [(0, '0%'), (5, '5%'), (12, '12%'), (18, '18%')]
VOLUMETRIC_DIVISOR = 5000      # L x W x H (cm) / 5000 = kg
EXPIRY_WARN_DAYS = 60          # 'expiring soon' window


class ProductVariant(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='variants')
    # Denormalised so the SKU can be unique per seller at the database level.
    seller = models.ForeignKey('sellers.SellerProfile', on_delete=models.CASCADE, related_name='variants')
    label = models.CharField(max_length=80, help_text='e.g. 1 kg Chocolate')
    sku = models.CharField(max_length=40)
    mrp = models.DecimalField(max_digits=10, decimal_places=2)
    price = models.DecimalField('Selling price', max_digits=10, decimal_places=2)
    moq = models.PositiveIntegerField('Minimum order quantity', default=1)
    stock = models.PositiveIntegerField(default=0)
    low_stock_threshold = models.PositiveIntegerField(default=10)
    batch_number = models.CharField(max_length=40, blank=True)
    manufactured_on = models.DateField(null=True, blank=True)
    expires_on = models.DateField(null=True, blank=True)
    hsn_code = models.CharField('HSN code', max_length=10, blank=True)
    gst_rate = models.PositiveSmallIntegerField(default=18, choices=GST_RATES)
    country_of_origin = models.CharField(max_length=60, default='India')
    dispatch_days = models.PositiveSmallIntegerField(default=2)
    # Shipping package: dimensions in cm, dead weight in grams.
    length_cm = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    width_cm = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    height_cm = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    weight_g = models.PositiveIntegerField('Dead weight (g)', null=True, blank=True)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['sort_order', 'id']
        constraints = [
            models.UniqueConstraint(fields=['seller', 'sku'], name='uniq_sku_per_seller'),
            models.CheckConstraint(condition=models.Q(price__lte=models.F('mrp')), name='variant_price_lte_mrp'),
        ]
        indexes = [models.Index(fields=['expires_on']), models.Index(fields=['stock'])]

    def __str__(self):
        return f'{self.product.name} - {self.label}'

    # ---- shipping weights ----
    @property
    def has_dimensions(self):
        return all(v and v > 0 for v in (self.length_cm, self.width_cm, self.height_cm)) and bool(self.weight_g)

    @property
    def volumetric_kg(self):
        return volumetric_weight_kg(self.length_cm, self.width_cm, self.height_cm)

    @property
    def chargeable_kg(self):
        return chargeable_weight_kg(self.weight_g, self.length_cm, self.width_cm, self.height_cm)

    @property
    def days_to_expiry(self):
        from datetime import date
        return (self.expires_on - date.today()).days if self.expires_on else None

    @property
    def is_expired(self):
        d = self.days_to_expiry
        return d is not None and d < 0

    @property
    def is_expiring_soon(self):
        d = self.days_to_expiry
        return d is not None and 0 <= d <= EXPIRY_WARN_DAYS

    @property
    def is_low_stock(self):
        return self.stock <= self.low_stock_threshold

    @property
    def is_complete(self):
        """Ready for review: price, stock, expiry and full dimensions are all present."""
        return bool(self.price and self.stock > 0 and self.expires_on and self.has_dimensions)

    def clean(self):
        super().clean()
        errors = {}
        if self.price is not None and self.mrp is not None and self.price > self.mrp:
            errors['price'] = 'Selling price cannot be higher than MRP.'
        if self.manufactured_on and self.expires_on and self.expires_on <= self.manufactured_on:
            errors['expires_on'] = 'Expiry date must be after the manufacture date.'
        if self.gst_rate not in dict(GST_RATES):
            errors['gst_rate'] = 'GST rate must be 0, 5, 12 or 18.'
        if errors:
            raise ValidationError(errors)


def volumetric_weight_kg(length, width, height):
    """L x W x H / 5000, in kg, rounded to grams."""
    if not all(v and Decimal(v) > 0 for v in (length, width, height)):
        return Decimal('0.000')
    return (Decimal(length) * Decimal(width) * Decimal(height) / VOLUMETRIC_DIVISOR).quantize(Decimal('0.001'))


def chargeable_weight_kg(weight_g, length, width, height):
    """max(dead weight, volumetric weight) in kg."""
    dead = (Decimal(weight_g or 0) / 1000).quantize(Decimal('0.001'))
    return max(dead, volumetric_weight_kg(length, width, height))


def _gallery_path(instance, filename):
    return f'products/{instance.product_id}/{filename}'


class ProductImage(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(upload_to=_gallery_path)
    alt_text = models.CharField(max_length=160, blank=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['sort_order', 'id']


class ProductHighlight(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='highlights')
    text = models.CharField(max_length=140)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['sort_order', 'id']


class APlusImage(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='aplus_images')
    image = models.ImageField(upload_to=_gallery_path)
    caption = models.CharField(max_length=200, blank=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['sort_order', 'id']


class StockMovement(models.Model):
    """Append-only stock ledger. `delta` is signed; `balance_after` is the stock after the change."""

    class Kind(models.TextChoices):
        ADD = 'add', 'Stock added'
        REMOVE = 'remove', 'Stock removed'
        SET = 'set', 'Stock count set'
        SALE = 'sale', 'Sold'
        RETURN = 'return', 'Returned / cancelled'

    variant = models.ForeignKey(ProductVariant, on_delete=models.CASCADE, related_name='movements')
    kind = models.CharField(max_length=8, choices=Kind.choices)
    delta = models.IntegerField()
    balance_after = models.PositiveIntegerField()
    reason = models.CharField(max_length=160, blank=True)
    actor = models.ForeignKey('auth.User', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    reference = models.CharField(max_length=40, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']

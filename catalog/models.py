from django.core.exceptions import ValidationError
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
    seller = models.ForeignKey(
        'sellers.SellerProfile', on_delete=models.CASCADE, related_name='products'
    )
    subcategory = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        related_name='products',
        limit_choices_to={'parent__isnull': False},
    )
    name = models.CharField(max_length=160)
    brand = models.CharField(max_length=80, blank=True)
    sku = models.CharField(max_length=60, blank=True)
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    stock = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['is_active', 'created_at']),
            models.Index(fields=['brand']),
        ]

    def __str__(self):
        return self.name

    @property
    def category(self):
        """Derived from the subcategory."""
        return self.subcategory.parent

    def clean(self):
        super().clean()
        if self.subcategory_id and not self.subcategory.parent_id:
            raise ValidationError({'subcategory': 'Choose a subcategory, not a top-level category.'})

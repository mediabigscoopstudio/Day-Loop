"""Test-only data builders. They run inside the temporary test database."""
from datetime import date, timedelta
from decimal import Decimal
from itertools import count

from django.contrib.auth import get_user_model

from catalog.models import Category, Product, ProductVariant
from orders.models import Order, OrderItem
from sellers.models import SellerProfile

_n = count(1)


def make_user(prefix='u'):
    i = next(_n)
    user = get_user_model()(username=f'{prefix}{i}', email=f'{prefix}{i}@example.test')
    user.set_unusable_password()          # factory users never log in; avoids slow password hashing
    user.save()
    return user


def make_seller(name=None, status='approved'):
    i = next(_n)
    return SellerProfile.objects.create(
        user=make_user('s'), business_name=name or f'Seller {i}', status=status, gst_number='22AAAAA0000A1Z5',
    )


def make_category(name=None, parent=None):
    return Category.objects.create(name=name or f'Cat {next(_n)}', parent=parent)


def make_product(seller, subcategory, price='100', stock=10, **kw):
    """A product with one default variant. `product.variant`, `.price` and `.stock` are test conveniences."""
    inactive = kw.pop('is_active', True) is False
    sku = kw.pop('sku', None) or f'SKU{next(_n)}'
    kw.setdefault('status', Product.Status.INACTIVE if inactive else Product.Status.LIVE)
    p = Product.objects.create(seller=seller, subcategory=subcategory, name=kw.pop('name', f'Product {next(_n)}'), **kw)
    v = ProductVariant.objects.create(
        product=p, seller=seller, label='Default', sku=sku, mrp=Decimal(price), price=Decimal(price), stock=stock,
        expires_on=date.today() + timedelta(days=365), length_cm=10, width_cm=10, height_cm=10, weight_g=500,
    )
    p.variant, p.price, p.stock = v, v.price, v.stock
    return p


def make_order(customer, when, lines, status='delivered', payment='paid'):
    """lines: list of (product, quantity). `when` is an aware datetime."""
    order = Order.objects.create(customer=customer, placed_at=when, status=status, payment_status=payment, total=0)
    total = Decimal(0)
    for product, qty in lines:
        item = OrderItem.objects.create(order=order, product=product, variant=product.variant, quantity=qty, unit_price=product.price)
        total += item.line_total
    order.total = total
    order.save(update_fields=['total'])
    return order

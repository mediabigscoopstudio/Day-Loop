"""Test-only data builders. They run inside the temporary test database."""
from datetime import timedelta
from decimal import Decimal
from itertools import count

from django.contrib.auth import get_user_model

from catalog.models import Category, Product
from orders.models import Order, OrderItem
from sellers.models import SellerProfile

_n = count(1)


def make_user(prefix='u'):
    i = next(_n)
    return get_user_model().objects.create_user(f'{prefix}{i}', f'{prefix}{i}@example.test', 'x-Pass-12345')


def make_seller(name=None, status='approved'):
    i = next(_n)
    return SellerProfile.objects.create(
        user=make_user('s'), business_name=name or f'Seller {i}', status=status, gst_number='22AAAAA0000A1Z5',
    )


def make_category(name=None, parent=None):
    return Category.objects.create(name=name or f'Cat {next(_n)}', parent=parent)


def make_product(seller, subcategory, price='100', stock=10, **kw):
    return Product.objects.create(
        seller=seller, subcategory=subcategory, name=kw.pop('name', f'Product {next(_n)}'),
        price=Decimal(price), stock=stock, **kw,
    )


def make_order(customer, when, lines, status='delivered', payment='paid'):
    """lines: list of (product, quantity). `when` is an aware datetime."""
    order = Order.objects.create(customer=customer, placed_at=when, status=status, payment_status=payment, total=0)
    total = Decimal(0)
    for product, qty in lines:
        item = OrderItem.objects.create(order=order, product=product, quantity=qty, unit_price=product.price)
        total += item.line_total
    order.total = total
    order.save(update_fields=['total'])
    return order

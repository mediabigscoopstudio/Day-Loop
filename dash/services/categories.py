"""Category rules that need more than one row: delete guard and reordering."""
from django.db import transaction

from catalog.models import Category, Product


def delete_block_reason(category):
    """Return a human explanation when deletion must be refused, else ''."""
    if category.parent_id is None:
        n_children = category.children.count()
        if n_children:
            n_products = Product.objects.filter(subcategory__parent=category).count()
            extra = f' and {n_products} product{"s" if n_products != 1 else ""}' if n_products else ''
            return (f'“{category.name}” still has {n_children} subcategor{"ies" if n_children != 1 else "y"}{extra}. '
                    'Move or delete the subcategories first.')
        return ''
    n = category.products.count()
    if n:
        return (f'{n} product{"s are" if n != 1 else " is"} filed under “{category.name}”. '
                'Move them to another subcategory or deactivate the products first.')
    return ''


@transaction.atomic
def move(category, direction):
    """Swap with the neighbouring sibling and renumber so sort_order is always 0..n-1."""
    siblings = list(Category.objects.select_for_update().filter(parent=category.parent_id).order_by('sort_order', 'name', 'pk'))
    idx = next(i for i, c in enumerate(siblings) if c.pk == category.pk)
    j = idx - 1 if direction == 'up' else idx + 1
    if 0 <= j < len(siblings):
        siblings[idx], siblings[j] = siblings[j], siblings[idx]
    for pos, c in enumerate(siblings):
        if c.sort_order != pos:
            Category.objects.filter(pk=c.pk).update(sort_order=pos)

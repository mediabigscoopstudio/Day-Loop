from django.db.models import Count, Max, Prefetch
from django.shortcuts import get_object_or_404, render
from django.views import View

from catalog.models import Category

from .access import SuperuserRequiredMixin
from .base import DashPageView
from .forms import CategoryForm
from .htmx import trigger_response
from .services.categories import delete_block_reason, move


class CategoryListView(DashPageView):
    active = 'products'
    template_name = 'dash/categories.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        subs = Category.objects.annotate(pc=Count('products')).order_by('sort_order', 'name')
        ctx['categories'] = (
            Category.objects.filter(parent__isnull=True)
            .annotate(sub_count=Count('children', distinct=True), pc=Count('children__products', distinct=True))
            .prefetch_related(Prefetch('children', queryset=subs, to_attr='subs'))
            .order_by('sort_order', 'name')
        )
        return ctx


def _cat(pk):
    return get_object_or_404(Category.objects.select_related('parent'), pk=pk)


class CategoryFormView(SuperuserRequiredMixin, View):
    """Create (no pk) or edit (pk) in a popup. Invalid POST re-renders with inline errors (422)."""

    def _render(self, request, form, instance, status=200):
        return render(request, 'dash/categories/form_modal.html', {
            'form': form, 'instance': instance, 'modal_size': 'md',
            'post_url': f'/products/categories/{instance.pk}/edit/' if instance else '/products/categories/new/',
        }, status=status)

    def get(self, request, pk=None):
        instance = _cat(pk) if pk else None
        initial = {}
        if not instance and request.GET.get('parent', '').isdigit():
            initial['parent'] = int(request.GET['parent'])
        return self._render(request, CategoryForm(instance=instance, initial=initial), instance)

    def post(self, request, pk=None):
        instance = _cat(pk) if pk else None
        form = CategoryForm(request.POST, request.FILES, instance=instance)
        if not form.is_valid():
            return self._render(request, form, instance, status=422)
        obj = form.save(commit=False)
        if not instance:
            top = Category.objects.filter(parent=obj.parent).aggregate(m=Max('sort_order'))['m']
            obj.sort_order = 0 if top is None else top + 1
        obj.save()
        kind = 'Subcategory' if obj.parent_id else 'Category'
        return trigger_response(f'{kind} “{obj.name}” {"updated" if instance else "created"}.', events=('categories-changed',))


class CategoryToggleView(SuperuserRequiredMixin, View):
    def get(self, request, pk):
        c = _cat(pk)
        turning_off = c.is_active
        return render(request, 'ui/confirm_modal.html', {
            'modal_size': 'sm', 'variant': 'warning' if turning_off else 'neutral', 'icon': 'alert' if turning_off else 'check',
            'title': f'{"Deactivate" if turning_off else "Activate"} {"subcategory" if c.parent_id else "category"}',
            'message': f'{"Deactivate" if turning_off else "Activate"} “{c.name}”?',
            'consequence': ('It will no longer be offered when sellers add products and will be hidden on the storefront.'
                            if turning_off else 'It will be available to sellers and visible on the storefront again.'),
            'confirm_label': 'Deactivate' if turning_off else 'Activate', 'post_url': f'/products/categories/{c.pk}/toggle/',
        })

    def post(self, request, pk):
        c = _cat(pk)
        c.is_active = not c.is_active
        c.save(update_fields=['is_active'])
        return trigger_response(f'“{c.name}” {"activated" if c.is_active else "deactivated"}.', events=('categories-changed',))


class CategoryDeleteView(SuperuserRequiredMixin, View):
    def get(self, request, pk):
        c = _cat(pk)
        reason = delete_block_reason(c)
        if reason:
            return render(request, 'dash/categories/delete_blocked.html', {'category': c, 'reason': reason, 'modal_size': 'sm'})
        return render(request, 'ui/confirm_modal.html', {
            'modal_size': 'sm', 'variant': 'danger', 'icon': 'trash', 'title': 'Delete category',
            'message': f'Delete “{c.name}”?', 'consequence': 'This cannot be undone.',
            'confirm_label': 'Delete', 'post_url': f'/products/categories/{c.pk}/delete/',
        })

    def post(self, request, pk):
        c = _cat(pk)
        reason = delete_block_reason(c)       # re-checked on the server; the popup is not trusted
        if reason:
            return render(request, 'dash/categories/delete_blocked.html',
                          {'category': c, 'reason': reason, 'modal_size': 'sm'}, status=422)
        name = c.name
        c.delete()
        return trigger_response(f'“{name}” deleted.', events=('categories-changed',))


class CategoryMoveView(SuperuserRequiredMixin, View):
    def post(self, request, pk, direction):
        if direction not in ('up', 'down'):
            return render(request, 'dash/categories/delete_blocked.html', {'category': _cat(pk), 'reason': 'Invalid move.'}, status=400)
        move(_cat(pk), direction)
        return trigger_response(None, events=('categories-changed',), close=False)


class SubcategoryOptions(SuperuserRequiredMixin, View):
    """Dependent select: GET ?category=<id> -> <option> list of its active subcategories."""

    def get(self, request):
        cid = request.GET.get('category', '')
        subs = Category.objects.filter(parent_id=int(cid), is_active=True) if cid.isdigit() else Category.objects.none()
        return render(request, 'ui/partials/subcategory_options.html', {'subs': subs, 'selected': request.GET.get('selected', '')})

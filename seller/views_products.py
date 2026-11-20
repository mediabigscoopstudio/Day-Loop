"""Product editor: ONE long page with collapsible cards. Variants, gallery and A+ content use popups."""
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import render
from django.utils import timezone
from django.views import View

from catalog.models import Category, Product, ProductHighlight

from .access import ApprovedSellerMixin
from .base import ApprovedPageView, shell_context
from .forms_products import ProductForm, parse_highlights
from .services import products as svc

P = Product.Status


class SubcategoryOptionsView(ApprovedSellerMixin, View):
    """Read-only dependent select: the admin-managed subcategories of a category. Sellers cannot change categories."""

    def get(self, request):
        cid = request.GET.get('category', '')
        subs = Category.objects.filter(parent_id=int(cid), is_active=True) if cid.isdigit() else Category.objects.none()
        return render(request, 'ui/partials/subcategory_options.html', {'subs': subs, 'selected': request.GET.get('selected', '')})


def sections_with_problems(blockers):
    """Which cards to auto-open: the ones named by the review blockers."""
    opened = set()
    for b in blockers:
        low = b.lower()
        if any(w in low for w in ('name', 'category', 'thumbnail')):
            opened.add('basics')
        if 'variant' in low:
            opened.add('variants')
    return opened


class ProductEditView(ApprovedPageView):
    template_name = 'seller/products/edit.html'
    active = 'products'

    # ---- helpers ----
    def _product(self, pk):
        if pk is None:
            return None
        try:
            return svc.get_product(self.seller, pk)
        except Product.DoesNotExist:
            raise Http404

    def _context(self, product, form, **extra):
        ctx = shell_context(self.seller, 'products')
        sections, done, blockers = svc.readiness(product) if product else ([], 0, [])
        cat_id = ''
        sub_id = ''
        if form is not None:
            cat_id = str(form['category'].value() or '')
            sub_id = str(form['subcategory'].value() or '')
            if not cat_id and sub_id.isdigit():
                sub = Category.objects.filter(pk=int(sub_id)).first()
                cat_id = str(sub.parent_id) if sub else ''
        ctx.update(
            product=product, form=form, sections=sections, done=done, total=5, blockers=blockers,
            categories=Category.objects.filter(parent__isnull=True, is_active=True), options_url='/products/subcategory-options/',
            selected_category=cat_id, selected_sub=sub_id,
            subs=Category.objects.filter(parent_id=int(cat_id), is_active=True) if cat_id.isdigit() else Category.objects.none(),
            highlights=extra.pop('highlights', [h.text for h in product.highlights.all()] if product else []),
            gallery=product.images.all() if product else [], aplus=product.aplus_images.all() if product else [],
            gallery_max=svc.GALLERY_MAX, aplus_max=svc.APLUS_MAX, hl_min=svc.HIGHLIGHTS_MIN, hl_max=svc.HIGHLIGHTS_MAX,
            jump=[('basics', 'Basics'), ('variants', 'Variants'), ('media', 'Images & highlights'), ('seo', 'SEO'), ('aplus', 'A+ content')],
            open_sections=extra.pop('open_sections', set()), saved=self.request.GET.get('saved') == '1', **extra)
        return ctx

    def get(self, request, pk=None):
        product = self._product(pk)
        if product and product.status == P.PENDING:
            return HttpResponseRedirect('/products/?notice=review')
        form = ProductForm(instance=product) if product else ProductForm()
        return render(request, self.template_name, self._context(product, form, open_sections={'basics'} if not product else set()))

    def post(self, request, pk=None):
        product = self._product(pk)
        if product and product.status == P.PENDING:
            return HttpResponseRedirect('/products/?notice=review')
        was_live = bool(product and product.status == P.LIVE)
        form = ProductForm(request.POST, request.FILES, instance=product)
        highlights, hl_error = parse_highlights(request.POST)
        if not form.is_valid() or hl_error:
            open_sections = {'basics'} if form.errors else set()
            if hl_error:
                open_sections.add('media')
            if any(k.startswith('meta_') for k in form.errors):
                open_sections.add('seo')
            return render(request, self.template_name, self._context(
                product, form, highlights=highlights, hl_error=hl_error, open_sections=open_sections), status=422)

        obj = form.save(commit=False)
        obj.seller, obj.subcategory = self.seller, form.cleaned_data['subcategory']
        if not obj.pk:
            obj.status = P.DRAFT
        elif was_live:                                   # content edits to a live product go back through review
            obj.status, obj.submitted_at = P.PENDING, timezone.now()
        svc.autofill_seo(obj)
        obj.save()
        obj.highlights.all().delete()
        ProductHighlight.objects.bulk_create([ProductHighlight(product=obj, text=t, sort_order=i) for i, t in enumerate(highlights)])

        if request.POST.get('action') == 'submit' and obj.status in (P.DRAFT, P.REJECTED):
            try:
                svc.submit_for_review(self.seller, obj.pk)
            except svc.ProductError as e:
                obj.refresh_from_db()
                _, _, blockers = svc.readiness(obj)
                return render(request, self.template_name, self._context(
                    obj, ProductForm(instance=obj), submit_error=str(e), open_sections=sections_with_problems(blockers)), status=422)
            return HttpResponseRedirect('/products/?submitted=1')
        if was_live:
            return HttpResponseRedirect('/products/?resubmitted=1')
        return HttpResponseRedirect(f'/products/{obj.pk}/edit/?saved=1')

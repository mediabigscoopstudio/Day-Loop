"""Gallery (up to 8) and A+ content (up to 5) images. One implementation, configured per kind."""
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.views import View

from catalog.models import APlusImage, Product, ProductImage

from .uploads import validate_product_image
from .views_variants import ProductScopedView, trigger

KINDS = {
    'gallery': dict(model=ProductImage, rel='images', max=8, event='gallery-changed', label='image', text_field='alt_text', text_label='Description (alt text)', wide=False),
    'aplus': dict(model=APlusImage, rel='aplus_images', max=5, event='aplus-changed', label='A+ image', text_field='caption', text_label='Caption', wide=True),
}


class MediaView(ProductScopedView):
    kind = 'gallery'
    url_part = 'images'

    @property
    def cfg(self):
        return KINDS[self.kind]

    def items(self, product):
        return list(getattr(product, self.cfg['rel']).all())

    def item(self, product, iid):
        try:
            return getattr(product, self.cfg['rel']).get(pk=iid)
        except self.cfg['model'].DoesNotExist:
            raise Http404

    def blocked(self, request, product):
        return product.status == Product.Status.PENDING


class MediaList(MediaView):
    def get(self, request, pk):
        p = self.product(pk)
        return render(request, 'seller/products/media_list.html', {
            'product': p, 'items': self.items(p), 'cfg': self.cfg, 'kind': self.kind, 'locked': self.blocked(request, p)})


class MediaAdd(MediaView):
    def _ctx(self, p, **extra):
        return {'product': p, 'cfg': self.cfg, 'kind': self.kind, 'remaining': self.cfg['max'] - len(self.items(p)),
                'modal_size': 'md', 'sheet': True, **extra}

    def get(self, request, pk):
        p = self.product(pk)
        if self.blocked(request, p):
            return self.locked(request, p)
        return render(request, 'seller/products/media_add_modal.html', self._ctx(p))

    def post(self, request, pk):
        p = self.product(pk)
        if self.blocked(request, p):
            return self.locked(request, p)
        remaining = self.cfg['max'] - len(self.items(p))
        files = request.FILES.getlist('files')
        error = ''
        if not files:
            error = 'Choose at least one image.'
        elif len(files) > remaining:
            error = f'You can add {remaining} more {self.cfg["label"]}{"s" if remaining != 1 else ""} (limit {self.cfg["max"]}).'
        else:
            for f in files:
                try:
                    validate_product_image(f)
                except ValidationError as e:
                    error = f'{f.name}: {e.messages[0]}'
                    break
        if error:
            return render(request, 'seller/products/media_add_modal.html', self._ctx(p, error=error), status=422)
        text = request.POST.get('text', '').strip()[:200]
        base = len(self.items(p))
        for i, f in enumerate(files):
            kwargs = {'product': p, 'image': f, 'sort_order': base + i}
            if self.cfg['text_field'] and (len(files) == 1 or self.kind == 'gallery'):
                kwargs[self.cfg['text_field']] = text
            self.cfg['model'].objects.create(**kwargs)
        return trigger(f'{len(files)} {self.cfg["label"]}{"s" if len(files) != 1 else ""} added.', events=(self.cfg['event'],))


class MediaText(MediaView):
    """Edit the caption / alt text of one image."""

    def _ctx(self, p, it, **extra):
        return {'product': p, 'item': it, 'cfg': self.cfg, 'kind': self.kind, 'value': getattr(it, self.cfg['text_field']), 'modal_size': 'sm', **extra}

    def get(self, request, pk, iid):
        p = self.product(pk)
        if self.blocked(request, p):
            return self.locked(request, p)
        return render(request, 'seller/products/media_text_modal.html', self._ctx(p, self.item(p, iid)))

    def post(self, request, pk, iid):
        p = self.product(pk)
        if self.blocked(request, p):
            return self.locked(request, p)
        it = self.item(p, iid)
        setattr(it, self.cfg['text_field'], request.POST.get('text', '').strip()[:200])
        it.save(update_fields=[self.cfg['text_field']])
        return trigger('Saved.', events=(self.cfg['event'],))


class MediaMove(MediaView):
    def post(self, request, pk, iid, direction):
        p = self.product(pk)
        if self.blocked(request, p):
            return self.locked(request, p)
        self.item(p, iid)
        if direction not in ('up', 'down'):
            raise Http404
        with transaction.atomic():
            rows = list(getattr(p, self.cfg['rel']).select_for_update().order_by('sort_order', 'id'))
            idx = next(i for i, r in enumerate(rows) if r.pk == iid)
            j = idx - 1 if direction == 'up' else idx + 1
            if 0 <= j < len(rows):
                rows[idx], rows[j] = rows[j], rows[idx]
            for pos, r in enumerate(rows):
                if r.sort_order != pos:
                    type(r).objects.filter(pk=r.pk).update(sort_order=pos)
        return trigger(None, events=(self.cfg['event'],), close=False)


class MediaReorder(MediaView):
    """Drag-and-drop: POST ids=<comma list> in the new order. Must be exactly this product's images."""

    def post(self, request, pk):
        p = self.product(pk)
        if self.blocked(request, p):
            return self.locked(request, p)
        try:
            ids = [int(x) for x in request.POST.get('ids', '').split(',') if x.strip()]
        except ValueError:
            return HttpResponse(status=400)
        existing = {r.pk for r in self.items(p)}
        if set(ids) != existing or len(ids) != len(existing):
            return HttpResponse(status=400)
        with transaction.atomic():
            for pos, iid in enumerate(ids):
                self.cfg['model'].objects.filter(pk=iid, product=p).update(sort_order=pos)
        return HttpResponse(status=204)


class MediaDelete(MediaView):
    def get(self, request, pk, iid):
        p = self.product(pk)
        if self.blocked(request, p):
            return self.locked(request, p)
        self.item(p, iid)
        return render(request, 'ui/confirm_modal.html', {
            'modal_size': 'sm', 'variant': 'danger', 'icon': 'trash', 'title': f'Remove {self.cfg["label"]}',
            'message': f'Remove this {self.cfg["label"]}?', 'consequence': 'The file is deleted from your product.',
            'confirm_label': 'Remove', 'post_url': f'/products/{p.pk}/{self.url_part}/{iid}/delete/'})

    def post(self, request, pk, iid):
        p = self.product(pk)
        if self.blocked(request, p):
            return self.locked(request, p)
        it = self.item(p, iid)
        it.image.delete(save=False)
        it.delete()
        return trigger(f'{self.cfg["label"].capitalize()} removed.', events=(self.cfg['event'],))


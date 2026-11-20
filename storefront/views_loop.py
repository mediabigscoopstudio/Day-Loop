from django.http import HttpResponse
from django.shortcuts import render
from django.views import View
from django.db.models import Q

from . import cart as cart_ops
from .common import done, is_htmx, popup
from .selectors import visible_products, visible_variants

SLOTS = {'morning': 'Morning', 'midday': 'Midday', 'night': 'Night'}
SLOT_TIME_KW = {
    'morning': ('multivitamin', 'shilajit', 'ashwagandha', 'vitamin', 'ginseng'),
    'midday': ('whey', 'protein', 'bcaa', 'eaa', 'creatine'),
    'night': ('casein', 'magnesium', 'ashwagandha', 'triphala', 'sleep', 'zma'),
}


def _slot_or_404(slot):
    if slot not in SLOTS:
        raise ValueError('bad slot')
    return slot


class LoopRemindView(View):
    """Saves the monthly reminder day. Reminders are shown in-app; no email or SMS is sent yet."""
    def post(self, request):
        try:
            day = min(28, max(1, int(request.POST.get('day', 1))))
        except ValueError:
            day = 1
        request.session['loop_day'] = day
        return done(request, f'Reminder set for day {day} of each month.', refresh=False)


class LoopPickerView(View):
    """Popup listing products for one slot. Search looks across the whole catalogue."""
    def get(self, request, slot):
        if slot not in SLOTS:
            return HttpResponse(status=404)
        q = request.GET.get('q', '').strip()
        qs = visible_products()
        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(brand__icontains=q) | Q(seller__business_name__icontains=q))
        else:
            kw = Q()
            for w in SLOT_TIME_KW[slot]:
                kw |= Q(name__icontains=w) | Q(subcategory__name__icontains=w)
            qs = qs.filter(kw)
        from .selectors import decorate
        products = decorate(list(qs.order_by('-avg_rating', '-created_at')[:30]))
        for p in products:
            p.pick_variants = [v for v in p.active_variants if v.stock > 0]
        chosen = request.session.get('loop_items', {}).get(slot)
        ctx = {'slot': slot, 'slot_name': SLOTS[slot], 'q': q, 'products': products, 'chosen': chosen}
        if is_htmx(request) and request.headers.get('HX-Target') == 'loop-list':
            return render(request, 'storefront/partials/loop_picker_list.html', ctx)
        return popup(request, 'storefront/modals/loop_picker.html', ctx)


class LoopPickView(View):
    def post(self, request):
        slot = request.POST.get('slot', '')
        if slot not in SLOTS:
            return HttpResponse(status=422)
        vid = request.POST.get('variant_id', '')
        var = visible_variants().select_related('product').filter(pk=vid if vid.isdigit() else 0).first()
        if not var:
            resp = HttpResponse(status=422)
            resp['HX-Trigger'] = '{"toast": {"message": "That product is not available right now.", "level": "error"}}'
            return resp
        items = dict(request.session.get('loop_items', {}))
        items[slot] = var.pk
        request.session['loop_items'] = items
        return done(request, f'{var.product.name} is now your {SLOTS[slot].lower()} pick.')


class LoopUnpickView(View):
    def post(self, request):
        slot = request.POST.get('slot', '')
        items = dict(request.session.get('loop_items', {}))
        items.pop(slot, None)
        request.session['loop_items'] = items
        return done(request, f'Removed from your {SLOTS.get(slot, "").lower()} loop.')


class LoopAddView(View):
    def post(self, request):
        added = 0
        for vid in request.POST.getlist('variant_id'):
            if vid.isdigit() and visible_variants().filter(pk=int(vid)).exists():
                cart_ops.add_to_cart(request, int(vid), 1)
                added += 1
        if not added:
            resp = HttpResponse(status=422)
            resp['HX-Trigger'] = '{"toast": {"message": "Pick at least one product first.", "level": "error"}}'
            return resp
        msg = f"{added} loop item{'s' if added != 1 else ''} added to your cart."
        resp = done(request, msg, refresh=False)
        resp['HX-Trigger'] = '{"toast": {"message": "' + msg + '", "level": "success"}, "cartChanged": true}'
        return resp

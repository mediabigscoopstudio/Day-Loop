from django.db.models import Count, Q, Sum
from django.http import Http404
from django.shortcuts import get_object_or_404, render
from django.views import View

from orders.models import OrderItem
from sellers.models import SellerProfile

from .access import SuperuserRequiredMixin
from .base import DashPageView
from .htmx import trigger_response
from .listing import apply_sort, clean_params, paginate
from .services.seller_decisions import ACTIONS, DecisionError, allowed_actions, decide

S = SellerProfile.Status
TABS = [('', 'All'), (S.PENDING, 'Pending'), (S.APPROVED, 'Approved'), (S.REJECTED, 'Rejected'), (S.NEEDS_INFO, 'Needs info')]
SORTS = {'name': 'business_name', 'applied': 'applied_at', 'status': 'status', 'city': 'city', 'products': 'product_count'}


class SellerListView(DashPageView):
    active = 'sellers'
    template_name = 'dash/sellers.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        p = clean_params(self.request.GET, ['status', 'q'])
        counts = SellerProfile.objects.aggregate(
            all=Count('id'),
            **{s.value: Count('id', filter=Q(status=s)) for s in S},
        )
        qs = SellerProfile.objects.select_related('user', 'category').annotate(product_count=Count('products'))
        if p.get('status') in S.values:
            qs = qs.filter(status=p['status'])
        if p.get('q'):
            q = p['q']
            qs = qs.filter(
                Q(business_name__icontains=q) | Q(user__email__icontains=q) | Q(user__username__icontains=q)
                | Q(gst_number__icontains=q) | Q(city__icontains=q)
            )
        qs, sort, desc = apply_sort(qs, self.request.GET, SORTS, ['-applied_at'])
        ctx.update(
            page=paginate(qs, self.request.GET), counts=counts, status=p.get('status', ''), q=p.get('q', ''),
            tabs=[(v, label, counts['all'] if v == '' else counts[v]) for v, label in TABS],
        )
        return ctx


def _seller_or_404(pk):
    return get_object_or_404(SellerProfile.objects.select_related('user', 'category'), pk=pk)


class SellerDetailModal(SuperuserRequiredMixin, View):
    def get(self, request, pk):
        seller = _seller_or_404(pk)
        stats = OrderItem.objects.filter(seller=seller).exclude(order__status='cancelled').aggregate(
            gmv=Sum('line_total'), orders=Count('order', distinct=True))
        return render(request, 'dash/sellers/detail_modal.html', {
            'seller': seller,
            'history': seller.history.select_related('actor'),
            'stats': stats, 'product_count': seller.products.count(),
            'actions': allowed_actions(seller),
        })


COPY = {
    'approve': dict(variant='neutral', icon='check', title='Approve seller', label='Approve seller',
                    consequence='The seller will be able to list products and receive orders.'),
    'reject': dict(variant='danger', icon='x', title='Reject seller', label='Reject seller',
                   consequence='The seller will not be able to list products or receive orders.',
                   reason=True, reason_label='Reason for rejection'),
    'request-info': dict(variant='warning', icon='info', title='Request more information', label='Send request',
                         consequence='The application stays on hold until the seller responds.',
                         reason=True, reason_label='What information is needed?'),
}


class SellerActionView(SuperuserRequiredMixin, View):
    def _ctx(self, seller, action, **extra):
        c = COPY[action]
        ctx = {
            'modal_size': 'sm', 'variant': c['variant'], 'icon': c['icon'], 'title': c['title'],
            'message': f'{c["title"]}: {seller.business_name}?', 'consequence': c['consequence'],
            'confirm_label': c['label'], 'post_url': f'/sellers/{seller.pk}/{action}/',
            'reason': c.get('reason', False), 'reason_label': c.get('reason_label'),
        }
        ctx.update(extra)
        return ctx

    def _check(self, action):
        if action not in ACTIONS:
            raise Http404

    def get(self, request, pk, action):
        self._check(action)
        return render(request, 'ui/confirm_modal.html', self._ctx(_seller_or_404(pk), action))

    def post(self, request, pk, action):
        self._check(action)
        seller = _seller_or_404(pk)
        reason = request.POST.get('reason', '')
        try:
            seller = decide(pk, action, request.user, reason)
        except DecisionError as e:
            err = str(e)
            extra = {'reason_value': reason}
            if 'reason' in err.lower():
                extra['reason_error'] = err
            else:
                extra['form_error'] = err
            return render(request, 'ui/confirm_modal.html', self._ctx(seller, action, **extra), status=422)
        verb = ACTIONS[action]['verb']
        return trigger_response(f'{seller.business_name} {verb}.', events=('sellers-changed',))

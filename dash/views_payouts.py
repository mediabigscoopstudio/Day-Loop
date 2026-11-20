"""Admin payouts: sellers with a pending balance, settle popup, recent payouts."""
from django.db.models import Count, DecimalField, F, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, render
from django.views import View

from orders.models import LedgerEntry, Payout
from orders.services import payouts as svc
from sellers.models import SellerProfile

from .access import SuperuserRequiredMixin
from .base import DashPageView
from .htmx import trigger_response

Z = Value(0, output_field=DecimalField(max_digits=14, decimal_places=2))


class PayoutListView(DashPageView):
    active = 'payouts'
    template_name = 'dash/payouts.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        rows = (LedgerEntry.objects.filter(payout__isnull=True)
                .values('seller', name=F('seller__business_name'))
                .annotate(credits=Coalesce(Sum('amount', filter=Q(kind='credit')), Z), debits=Coalesce(Sum('amount', filter=Q(kind='debit')), Z),
                          entries=Count('id'))
                .order_by('name'))
        rows = list(rows)
        for r in rows:
            r['pending'] = r['credits'] - r['debits']
        ctx.update(rows=rows, recent=Payout.objects.select_related('seller', 'created_by')[:15],
                   total_pending=sum((r['pending'] for r in rows if r['pending'] > 0), 0))
        return ctx


class SettleView(SuperuserRequiredMixin, View):
    def _seller(self, pk):
        return get_object_or_404(SellerProfile, pk=pk)

    def _ctx(self, s, **extra):
        from orders.services.payouts import balances
        b = balances(s)
        return {'modal_size': 'sm', 'variant': 'warning', 'icon': 'rupee', 'title': 'Settle payout',
                'message': f'Pay {s.business_name} {b["pending"]:.2f}?',
                'consequence': 'Mark this amount as paid out. Make sure the bank transfer is done; this cannot be undone.',
                'confirm_label': 'Mark as paid', 'post_url': f'/payouts/{s.pk}/settle/', 'reason': True,
                'reason_label': 'Bank reference (optional)', **extra}

    def get(self, request, pk):
        return render(request, 'dash/payouts/settle_modal.html', self._ctx(self._seller(pk)))

    def post(self, request, pk):
        s = self._seller(pk)
        try:
            payout = svc.settle(s.pk, request.user, request.POST.get('reference', ''))
        except svc.SettlementError as e:
            return render(request, 'dash/payouts/settle_modal.html', self._ctx(s, form_error=str(e)), status=422)
        return trigger_response(f'Paid {s.business_name} ₹{payout.amount:.2f}.', events=('payouts-changed',))

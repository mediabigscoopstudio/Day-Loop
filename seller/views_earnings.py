"""Earnings: pending vs settled payouts, ledger and payout history. Read-only for sellers."""
from dash.listing import paginate
from orders.models import LedgerEntry, Payout
from orders.services.payouts import balances

from .base import ApprovedPageView


class EarningsView(ApprovedPageView):
    template_name = 'seller/earnings.html'
    active = 'earnings'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ledger = LedgerEntry.objects.filter(seller=self.seller).select_related('seller_order', 'payout')
        ctx.update(
            bal=balances(self.seller), page=paginate(ledger, self.request.GET, per_page=12),
            payouts=Payout.objects.filter(seller=self.seller)[:10])
        return ctx

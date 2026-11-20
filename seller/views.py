from django.http import HttpResponseRedirect

from sellers.models import SellerProfile

from .base import SellerPageView


class StatusView(SellerPageView):
    active = 'home'
    template_name = 'seller/status.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        s = self.seller
        history = list(s.history.select_related('actor')[:10])
        last_by_status = {}
        for h in history:
            last_by_status.setdefault(h.to_status, h)
        ctx.update(
            history=history, S=SellerProfile.Status,
            rejection=last_by_status.get('rejected') if s.status == s.Status.REJECTED else None,
            info_request=last_by_status.get('needs_info') if s.status == s.Status.NEEDS_INFO else None,
            replies=s.info_replies.all()[:5], welcome=self.request.GET.get('welcome') == '1',
        )
        return ctx


from django.http import JsonResponse  # noqa: E402
from django.views import View  # noqa: E402

from dash.services.dates import PRESETS, parse_range  # noqa: E402
from orders.models import Payout  # noqa: E402

from .access import ApprovedSellerMixin  # noqa: E402
from .services import metrics  # noqa: E402

SELLER_PRESETS = [p for p in PRESETS if p[0] in ('7d', '30d', '90d', '12m')]


class DashboardView(SellerPageView):
    """Approved sellers' overview."""
    active = 'home'
    template_name = 'seller/home.html'

    def get(self, request, *args, **kwargs):
        if not self.seller.is_approved:
            return HttpResponseRedirect('/status/')
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        dr = parse_range(self.request.GET)
        basis = self.request.GET.get('basis', 'gmv')
        k = metrics.kpis(self.seller, dr, basis)
        ctx.update(
            dr=dr, presets=SELLER_PRESETS, kpis=k['cards'], basis=k['basis'], actions=metrics.needs_action(self.seller),
            low_stock=list(metrics.low_stock_qs(self.seller).order_by('stock')[:6]), top_products=metrics.top_products(self.seller, dr),
            recent_payouts=Payout.objects.filter(seller=self.seller)[:5])
        return ctx


class SalesApi(ApprovedSellerMixin, View):
    def get(self, request):
        dr = parse_range(request.GET)
        return JsonResponse(metrics.sales_series(self.seller, dr, request.GET.get('basis', 'gmv')))

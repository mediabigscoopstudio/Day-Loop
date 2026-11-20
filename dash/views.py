"""Overview page, its HTMX partials and JSON endpoints. All require a superuser."""
from django.http import JsonResponse
from django.shortcuts import render
from django.views import View

from .access import SuperuserRequiredMixin
from .base import DashPageView
from .services import metrics
from .services.dates import PRESETS, parse_range


class RangeMixin:
    """Adds `self.dr` parsed from ?range= / ?start= / ?end=."""

    def dispatch(self, request, *args, **kwargs):
        self.dr = parse_range(request.GET)
        return super().dispatch(request, *args, **kwargs)


class OverviewView(RangeMixin, DashPageView):
    active = 'overview'
    template_name = 'dash/overview.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        kpis = metrics.overview_kpis(self.dr)
        gmv = next(k for k in kpis if k['key'] == 'gmv')
        ctx.update(
            dr=self.dr, presets=PRESETS, kpis=kpis,
            gmv_total=gmv['value'], gmv_delta=gmv['delta'],
            top_sellers=metrics.top_sellers(self.dr),
            pending=metrics.pending_sellers(), pending_total=metrics.pending_total(),
            recent_orders=metrics.recent_orders(),
        )
        return ctx


class KpiPartial(SuperuserRequiredMixin, RangeMixin, View):
    def get(self, request):
        return render(request, 'dash/partials/kpis.html', {'kpis': metrics.overview_kpis(self.dr)})


class PendingPartial(SuperuserRequiredMixin, View):
    def get(self, request):
        return render(request, 'dash/partials/pending_approvals.html', {
            'rows': metrics.pending_sellers(), 'pending_total': metrics.pending_total()})


class RecentOrdersPartial(SuperuserRequiredMixin, View):
    def get(self, request):
        return render(request, 'dash/partials/recent_orders.html', {'rows': metrics.recent_orders()})


class SalesApi(SuperuserRequiredMixin, RangeMixin, View):
    def get(self, request):
        return JsonResponse(metrics.sales_series(self.dr))


class CategoryRevenueApi(SuperuserRequiredMixin, RangeMixin, View):
    def get(self, request):
        level = 'subcategory' if request.GET.get('level') == 'subcategory' else 'category'
        return JsonResponse(metrics.category_revenue(self.dr, level=level))


class NewVsRepeatApi(SuperuserRequiredMixin, RangeMixin, View):
    def get(self, request):
        return JsonResponse(metrics.new_vs_repeat(self.dr))


class AnalyticsView(RangeMixin, DashPageView):
    active = 'analytics'
    template_name = 'dash/analytics.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        kpis = {k['key']: k for k in metrics.overview_kpis(self.dr)}
        ctx.update(
            dr=self.dr, presets=PRESETS, kpis=kpis,
            top_sellers=metrics.top_sellers(self.dr, limit=8), top_products=metrics.top_products(self.dr),
            cohorts=metrics.repeat_cohorts(),
        )
        return ctx

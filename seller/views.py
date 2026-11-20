from django.http import HttpResponseRedirect

from sellers.models import SellerProfile

from .base import SellerPageView


class HomeView(SellerPageView):
    """Overview for approved sellers; everyone else is sent to the status page."""
    active = 'home'
    template_name = 'seller/home.html'

    def get(self, request, *args, **kwargs):
        if not self.seller.is_approved:
            return HttpResponseRedirect('/status/')
        return super().get(request, *args, **kwargs)


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

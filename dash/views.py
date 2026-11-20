from .base import DashPageView


class OverviewView(DashPageView):
    active = 'overview'
    template_name = 'dash/overview.html'

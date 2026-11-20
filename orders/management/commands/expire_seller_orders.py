"""Cancel seller orders that were not accepted in time (stock returns). Schedule it, e.g. every 15 minutes:

    */15 * * * *  python manage.py expire_seller_orders
"""
from django.core.management.base import BaseCommand

from orders.services.seller_flow import expire_unaccepted


class Command(BaseCommand):
    help = 'Cancel NEW seller orders past their accept-by time and return their stock.'

    def handle(self, *args, **opts):
        n = expire_unaccepted()
        self.stdout.write(self.style.SUCCESS(f'Cancelled {n} unaccepted seller order(s).'))

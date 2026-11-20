import json
from datetime import date, timedelta

from catalog.models import ProductVariant, StockMovement
from dash.tests import factories as f

from .product_helpers import HX, ProductCase


class InventoryBase(ProductCase):
    def setUp(self):
        super().setUp()
        today = date.today()
        mk = lambda name, stock, exp, thr=10: self._mk(name, stock, exp, thr)
        self.ok = mk('Plenty', 100, today + timedelta(days=400))
        self.low = mk('Running Low', 4, today + timedelta(days=400))
        self.out = mk('Sold Out', 0, today + timedelta(days=400))
        self.soon = mk('Expires Soon', 50, today + timedelta(days=30))
        self.old = mk('Expired', 50, today - timedelta(days=5))
        self.theirs = f.make_product(self.b, self.sub, '100', stock=3, name='Beta Secret').variant

    def _mk(self, name, stock, exp, thr):
        v = f.make_product(self.a, self.sub, '100', stock=stock, name=name).variant
        ProductVariant.objects.filter(pk=v.pk).update(expires_on=exp, low_stock_threshold=thr, batch_number=f'B-{name[:3]}')
        return v


class InventoryListTests(InventoryBase):
    def names(self, qs=''):
        r = self.client.get('/inventory/' + qs)
        self.assertEqual(r.status_code, 200, qs)
        return {v.product.name for v in r.context['page'].object_list}

    def test_only_my_variants_and_filters(self):
        self.assertEqual(len(self.names()), 5); self.assertNotIn('Beta Secret', self.names())
        self.assertEqual(self.names('?filter=low'), {'Running Low'})
        self.assertEqual(self.names('?filter=out'), {'Sold Out'})
        self.assertEqual(self.names('?filter=expiring'), {'Expires Soon'})
        self.assertEqual(self.names('?filter=expired'), {'Expired'})
        self.assertEqual(self.names('?q=B-Run'), {'Running Low'})                          # batch search
        self.assertEqual(len(self.names('?filter=zzz&page=abc')), 5)

    def test_summary_counts_and_badges(self):
        r = self.client.get('/inventory/')
        self.assertEqual((r.context['n_low'], r.context['n_out'], r.context['n_expiring'], r.context['n_expired']), (1, 1, 1, 1))
        for text in ('Expires in 30 days', 'Expired ', '4 low', 'Batch B-Run'):
            self.assertContains(r, text)

    def test_model_expiry_helpers(self):
        self.soon.refresh_from_db()
        self.assertTrue(self.soon.is_expiring_soon and not self.soon.is_expired)
        self.old.refresh_from_db(); self.assertTrue(self.old.is_expired and not self.old.is_expiring_soon)
        self.assertEqual(self.soon.days_to_expiry, 30)

    def test_empty_state(self):
        ProductVariant.objects.filter(seller=self.a).delete()
        self.assertContains(self.client.get('/inventory/'), 'No stock to track yet')


class StockUpdateTests(InventoryBase):
    def post(self, v, **d):
        return self.client.post(f'/inventory/{v.pk}/stock/', d, **HX)

    def test_add_remove_set_with_reasons_write_movements(self):
        r = self.post(self.low, action='add', quantity='20', reason='New batch received')
        self.assertEqual(r.status_code, 204)
        self.assertTrue(json.loads(r['HX-Trigger'])['inventory-changed'])
        self.post(self.low, action='remove', quantity='4', reason='Damaged in storage')
        self.post(self.low, action='set', quantity='50', reason='Cycle count')
        self.low.refresh_from_db(); self.assertEqual(self.low.stock, 50)
        rows = list(StockMovement.objects.filter(variant=self.low).order_by('id').values_list('kind', 'delta', 'balance_after', 'reason'))
        self.assertEqual(rows, [('add', 20, 24, 'New batch received'), ('remove', -4, 20, 'Damaged in storage'), ('set', 30, 50, 'Cycle count')])
        self.assertEqual(StockMovement.objects.get(reason='Cycle count').actor, self.a.user)

    def test_reason_is_required_and_stock_cannot_go_negative(self):
        self.assertContains(self.post(self.low, action='add', quantity='5', reason='  '), 'give a reason', status_code=422)
        r = self.post(self.low, action='remove', quantity='99', reason='Oops')
        self.assertContains(r, 'Only 4', status_code=422)
        self.low.refresh_from_db(); self.assertEqual(self.low.stock, 4)
        self.assertFalse(StockMovement.objects.filter(variant=self.low).exists())
        for bad in ({'action': 'sale', 'quantity': '1'}, {'action': 'add', 'quantity': '-3'}, {'action': 'add', 'quantity': 'x'}):
            self.assertEqual(self.post(self.low, reason='r', **bad).status_code, 422, bad)

    def test_modal_shows_current_stock_and_is_a_bottom_sheet(self):
        r = self.client.get(f'/inventory/{self.low.pk}/stock/', **HX)
        self.assertContains(r, 'now <strong>4</strong>'); self.assertContains(r, 'sheet')

    def test_history_popup(self):
        self.post(self.low, action='add', quantity='1', reason='Top up')
        r = self.client.get(f'/inventory/{self.low.pk}/history/', **HX)
        self.assertContains(r, 'Top up'); self.assertContains(r, '+1')
        self.assertContains(self.client.get(f'/inventory/{self.ok.pk}/history/', **HX), 'No movements yet')


class InventoryAccessTests(InventoryBase):
    def test_other_sellers_variants_are_404_and_unchanged(self):
        for method, url in (('get', f'/inventory/{self.theirs.pk}/stock/'), ('post', f'/inventory/{self.theirs.pk}/stock/'),
                            ('get', f'/inventory/{self.theirs.pk}/history/')):
            r = getattr(self.client, method)(url, {'action': 'set', 'quantity': '999', 'reason': 'x'}, **HX)
            self.assertEqual(r.status_code, 404, url)
        self.theirs.refresh_from_db(); self.assertEqual(self.theirs.stock, 3)
        self.assertFalse(StockMovement.objects.filter(variant=self.theirs).exists())

    def test_unapproved_and_non_sellers_denied(self):
        for user in (self.pending.user, self.customer):
            self.login_as(user)
            self.assertEqual(self.client.get('/inventory/', **HX).status_code, 403)
            self.assertEqual(self.client.post(f'/inventory/{self.ok.pk}/stock/', {'action': 'add', 'quantity': 1, 'reason': 'x'}, **HX).status_code, 403)
        self.login_as(self.pending.user)
        self.assertEqual(self.client.get('/inventory/')['Location'], '/status/')

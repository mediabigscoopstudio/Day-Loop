"""
Phone checks at a 390 px design width. These are template/CSS tests (no visual checks):
they assert the markup and rules that make the portal usable on a phone.
"""
import re
from pathlib import Path

from django.contrib.staticfiles import finders

from dash.tests import factories as f

from .onboarding_helpers import STEP1, OnboardingCase
from .product_helpers import HX, ProductCase

WIDTH = 390


def css(name):
    return Path(finders.find(name)).read_text()


class PhoneShellTests(ProductCase):
    def test_every_page_declares_a_device_width_viewport(self):
        for url in ('/', '/products/', '/inventory/', '/orders/', '/earnings/', '/account/', '/products/new/'):
            r = self.client.get(url)
            self.assertContains(r, '<meta name="viewport" content="width=device-width, initial-scale=1">', msg_prefix=url)

    def test_approved_sellers_get_the_five_tab_bar_and_a_floating_add_button(self):
        r = self.client.get('/')
        tabs = re.findall(r'<nav class="tabbar".*?</nav>', r.content.decode(), re.S)[0]
        for href, label in (('/', 'Home'), ('/products/', 'Products'), ('/inventory/', 'Inventory'), ('/orders/', 'Orders'), ('/account/', 'Account')):
            self.assertIn(f'href="{href}"', tabs); self.assertIn(f'<span>{label}</span>', tabs)
        self.assertEqual(tabs.count('<a '), 5)
        self.assertContains(r, 'class="fab" href="/products/new/"'); self.assertContains(r, 'aria-label="Add product"')
        self.assertContains(self.client.get('/orders/'), 'aria-current="page"')

    def test_unapproved_sellers_get_no_tab_bar_or_add_button(self):
        self.login_as(self.pending.user)
        r = self.client.get('/status/')
        self.assertNotContains(r, 'class="tabbar"'); self.assertNotContains(r, 'class="fab"')

    def test_css_enforces_44px_targets_16px_inputs_and_single_column_forms(self):
        shell = css('ui/css/shell.css')
        phone = shell[shell.index('/* Phones: 44px'):]
        self.assertIn('min-height: 44px', phone); self.assertIn('min-height: 48px; font-size: 16px', phone)
        self.assertIn('.form-cols, .cols-2, .filter-grid, .review-grid { grid-template-columns: 1fr !important; }', phone)
        self.assertRegex(shell, r'\.tabbar a \{[^}]*min-height: 56px')
        self.assertRegex(shell, r'\.fab \{[^}]*width: 56px; height: 56px')
        self.assertIn('max-width: 860px', shell)                                       # phone breakpoint covers 390 px
        self.assertLess(WIDTH, 860)
        self.assertRegex(css('seller/css/seller.css'), r'\.action-bar \.btn \{ flex: 1; min-height: 48px; \}')

    def test_product_editor_has_a_sticky_action_bar_and_collapsible_cards(self):
        p = f.make_product(self.a, self.sub, '500', stock=5, status='draft', name='Whey')
        r = self.client.get(f'/products/{p.pk}/edit/')
        self.assertContains(r, 'class="action-bar"'); self.assertContains(r, 'name="action" value="draft"'); self.assertContains(r, 'name="action" value="submit"')
        self.assertEqual(len(re.findall(r'<details class="pcard"', r.content.decode())), 5)
        self.assertRegex(css('seller/css/seller.css'), r'\.action-bar \{[^}]*position: fixed')

    def test_lists_render_cards_for_phones(self):
        f.make_product(self.a, self.sub, '500', stock=5, name='Whey')
        for url in ('/products/', '/inventory/'):
            self.assertContains(self.client.get(url), 'card-list show-mobile', msg_prefix=url)
        self.assertRegex(css('seller/css/seller.css'), r'@media \(max-width: 860px\) \{ \.show-desktop \{ display: none; \} \.show-mobile \{ display: grid; \} \}')

    def test_popups_are_bottom_sheets_on_phones(self):
        p = f.make_product(self.a, self.sub, '500', stock=5, status='draft', name='Whey')
        v = p.variant
        for url in (f'/products/{p.pk}/variants/new/', f'/products/{p.pk}/variants/sizes/', f'/inventory/{v.pk}/stock/', f'/products/{p.pk}/images/add/',
                    '/account/profile/', '/account/bank/', '/account/password/'):
            self.assertContains(self.client.get(url, **HX), 'sheet', msg_prefix=url)
        modal = css('ui/css/modal.css')
        self.assertIn('dialog.modal.sheet { width: 100vw;', modal); self.assertIn('border-radius: 22px 22px 0 0', modal)
        self.assertIn('position: sticky; bottom: 0', modal)

    def test_forms_use_phone_friendly_input_types(self):
        v = self.client.get(f'/products/{f.make_product(self.a, self.sub, "5", stock=1, status="draft").pk}/variants/new/', **HX)
        for attr in ('inputmode="decimal"', 'inputmode="numeric"', 'type="date"'):
            self.assertContains(v, attr)


class PhoneUploadTests(OnboardingCase):
    def test_document_fields_offer_camera_and_gallery(self):
        self.client.post('/onboarding/step/1/', STEP1, **HX)
        r = self.client.get('/onboarding/?step=2', **HX)
        html = r.content.decode()
        self.assertGreaterEqual(html.count('capture="environment"'), 8)                 # one camera input per document field
        self.assertIn('accept="image/*,application/pdf"', html)
        self.assertIn('Take photo', html); self.assertIn('Choose file', html)
        self.assertIn('class="dropzone" data-dropzone', html)                          # drag-drop for desktop

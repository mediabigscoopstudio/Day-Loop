import shutil
import tempfile

from django.test import override_settings

from catalog.models import Category, Product
from dash.tests import factories as f

from .base import SellerTestCase
from .onboarding_helpers import png  # noqa: F401  (re-exported for tests)

HX = {'HTTP_HX_REQUEST': 'true'}


class ProductCase(SellerTestCase):
    """Approved seller A is logged in. Uploads go to a temporary MEDIA_ROOT, never the project's media/."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._media = tempfile.mkdtemp(prefix='dl_test_media_')
        cls._override = override_settings(MEDIA_ROOT=cls._media)
        cls._override.enable()

    @classmethod
    def tearDownClass(cls):
        cls._override.disable()
        shutil.rmtree(cls._media, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        self.cat = Category.objects.create(name='Wellness')
        self.sub = Category.objects.create(name='Protein', parent=self.cat)
        self.cat2 = Category.objects.create(name='Care')
        self.sub2 = Category.objects.create(name='Skin', parent=self.cat2)
        self.login_as(self.a.user)

    def product(self, seller=None, status='draft', **kw):
        p = Product.objects.create(seller=seller or self.a, subcategory=self.sub, name=kw.pop('name', 'Whey'), status=status, **kw)
        return p

    def ready_product(self, seller=None, **kw):
        """A draft that passes every review check."""
        s = seller or self.a
        p = f.make_product(s, self.sub, '500', stock=5, status='draft', **kw)
        Product.objects.filter(pk=p.pk).update(thumbnail='products/thumbs/t.png')
        return p

    def basics(self, **over):
        d = dict(category=self.cat.pk, subcategory=self.sub.pk, name='Whey Protein', brand='Alpha', short_description='Clean protein',
                 description='<p>Great <b>stuff</b></p>', meta_title='', meta_description='', meta_keywords='', action='draft')
        d.update(over)
        return d

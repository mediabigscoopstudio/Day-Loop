"""Shared helpers for onboarding tests. Uploads go to a temporary MEDIA_ROOT, never the project's media/."""
import io
import shutil
import tempfile
from datetime import date, timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from PIL import Image

from catalog.models import Category

from .base import SellerTestCase

HX = {'HTTP_HX_REQUEST': 'true'}


def png_bytes(size=(40, 40), color=(14, 77, 59)):
    buf = io.BytesIO()
    Image.new('RGB', size, color).save(buf, 'PNG')
    return buf.getvalue()


def png(name='x.png', **kw):
    return SimpleUploadedFile(name, png_bytes(**kw), content_type='image/png')


def pdf(name='x.pdf'):
    return SimpleUploadedFile(name, b'%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF', content_type='application/pdf')


STEP1 = dict(legal_name='Fresh Roots Pvt Ltd', business_name='Fresh Roots', business_type='manufacturer',
             contact_person='Asha Rao', phone='9876543210', email='asha@fresh.example', city='Pune',
             address='12 MG Road, Pune 411001', year_established='2015')


def step2_data(**over):
    d = dict(gst_number='27ABCDE1234F1Z5', pan_number='ABCDE1234F', fssai_number='12345678901234',
             fssai_expiry=(date.today() + timedelta(days=400)).isoformat(), mfg_licence_number='')
    d.update(over)
    return d


def step2_files(**over):
    f = dict(doc_gst=png('gst.png'), doc_pan=pdf('pan.pdf'), doc_fssai=png('fssai.png'))
    f.update(over)
    return f


class OnboardingCase(SellerTestCase):
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
        self.cat2 = Category.objects.create(name='Care')
        self.me = self.draft                       # the seller under test (status = draft)
        self.login_as(self.me.user)

    def post_step(self, n, data=None, files=None, **extra):
        return self.client.post(f'/onboarding/step/{n}/', {**(data or {}), **(files or {})}, **HX, **extra)

    def bank_data(self, **over):
        d = dict(account_holder='Fresh Roots Pvt Ltd', account_number='918273645500', ifsc='HDFC0001234', bank_name='HDFC Bank',
                 upi_id='fresh@hdfc', categories=[self.cat.pk], dispatch_days='2', dispatch_address='')
        d.update(over)
        return d

    def complete_all_steps(self):
        assert self.post_step(1, STEP1).status_code == 200
        assert self.post_step(2, step2_data(), step2_files()).status_code == 200
        assert self.post_step(3, self.bank_data()).status_code == 200
        self.me.refresh_from_db()

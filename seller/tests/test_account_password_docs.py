import os
from datetime import date, timedelta

from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile

from sellers.models import SellerDocument

from .base import PW
from .product_helpers import HX, ProductCase, png

NEW_PW = 'Fresh-Secret-9921'


class PasswordTests(ProductCase):
    def change(self, **over):
        d = dict(current_password=PW, new_password=NEW_PW, confirm_password=NEW_PW)
        d.update(over)
        return self.client.post('/account/password/', d, **HX)

    def test_successful_change_keeps_this_session_and_switches_the_password(self):
        r = self.change()
        self.assertEqual(r.status_code, 204)
        self.assertEqual(self.client.get('/account/').status_code, 200)                # still signed in
        self.client.logout()
        self.assertContains(self.post_login(self.a.user.username, PW), 'Invalid credentials', status_code=400)
        self.assertEqual(self.post_login(self.a.user.username, NEW_PW).status_code, 302)

    def test_validation(self):
        cases = [({'current_password': 'wrong'}, 'not correct'), ({'confirm_password': 'different'}, 'do not match'),
                 ({'new_password': '12345678', 'confirm_password': '12345678'}, 'entirely numeric'),
                 ({'new_password': 'short', 'confirm_password': 'short'}, 'too short'),
                 ({'new_password': PW, 'confirm_password': PW}, 'different from your current')]
        for change, text in cases:
            self.assertContains(self.change(**change), text, status_code=422)
        self.a.user.refresh_from_db(); self.assertTrue(self.a.user.check_password(PW))

    def test_other_sessions_are_ended_after_a_change(self):
        from django.test import Client
        other = Client(HTTP_HOST='seller.localhost:8000')
        from django.test import override_settings
        with override_settings(SESSION_COOKIE_NAME='dl_seller_sid'):
            other.force_login(self.a.user)
        self.assertEqual(other.get('/account/').status_code, 200)
        self.change()
        self.assertEqual(other.get('/account/').status_code, 302)                      # the older session was invalidated

    def test_available_to_unapproved_sellers_but_not_to_others(self):
        self.login_as(self.pending.user)
        self.assertEqual(self.client.get('/account/password/', **HX).status_code, 200)
        self.login_as(self.customer)
        self.assertEqual(self.client.get('/account/password/', **HX).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.post('/account/password/', {}, **HX).status_code, 403)


class DocumentTests(ProductCase):
    def doc(self, kind='gst', expires=None, days=None):
        d = SellerDocument(seller=self.a, kind=kind, expires_on=expires if expires else (date.today() + timedelta(days=days) if days is not None else None))
        d.file.save(f'{kind}.png', ContentFile(b'x'), save=False); d.save()
        return d

    def upload(self, **over):
        data = dict(kind='gst', expires_on='')
        data.update(over)
        files = {'file': over.pop('file', None) or png('new.png')}
        data.pop('file', None)
        return self.client.post('/account/documents/', {**data, **files}, **HX)

    def test_replacing_a_document_swaps_the_row_and_deletes_the_old_file(self):
        old = self.doc('gst'); old_path = old.file.path
        self.assertTrue(os.path.exists(old_path))
        r = self.upload(kind='gst')
        self.assertEqual(r.status_code, 204)
        self.assertEqual(self.a.documents.filter(kind='gst').count(), 1)
        self.assertFalse(os.path.exists(old_path))
        self.assertTrue(self.a.documents.get(kind='gst').file.name.endswith('new.png'))

    def test_files_are_checked_by_content(self):
        fake = SimpleUploadedFile('a.pdf', b'MZ not a pdf', content_type='application/pdf')
        self.assertContains(self.upload(file=fake), 'photo (JPG/PNG) or a PDF', status_code=422)
        self.assertFalse(self.a.documents.exists())

    def test_fssai_needs_a_future_expiry_and_updates_the_profile(self):
        self.assertContains(self.upload(kind='fssai'), 'needs its expiry', status_code=422)
        past = (date.today() - timedelta(days=2)).isoformat()
        self.assertContains(self.upload(kind='fssai', expires_on=past), 'must be in the future', status_code=422)
        future = date.today() + timedelta(days=300)
        self.assertEqual(self.upload(kind='fssai', expires_on=future.isoformat()).status_code, 204)
        self.a.refresh_from_db(); self.assertEqual(self.a.fssai_expiry, future)

    def test_expiry_warnings_appear_on_the_account_page(self):
        self.doc('fssai', days=20); self.doc('gmp', days=-3); self.doc('gst', days=400)
        r = self.client.get('/account/')
        self.assertContains(r, 'FSSAI licence expires soon'); self.assertContains(r, 'GMP certificate has expired')
        self.assertEqual(len(r.context['warnings']), 2)                                # the GST document is fine
        self.assertContains(r, 'Upload the renewed document')

    def test_profile_fssai_expiry_also_warns_without_a_document(self):
        type(self.a).objects.filter(pk=self.a.pk).update(fssai_expiry=date.today() - timedelta(days=1))
        self.assertContains(self.client.get('/account/'), 'FSSAI licence has expired')

    def test_documents_are_scoped_to_me(self):
        theirs = SellerDocument(seller=self.b, kind='gst'); theirs.file.save('g.png', ContentFile(b'x'), save=False); theirs.save()
        r = self.client.get('/account/')
        self.assertNotContains(r, theirs.file.url)
        self.upload(kind='gst')
        self.assertTrue(SellerDocument.objects.filter(pk=theirs.pk).exists())          # B's document untouched
        self.assertEqual(self.b.documents.count(), 1)

    def test_unapproved_sellers_cannot_upload_here(self):
        self.login_as(self.pending.user)
        self.assertEqual(self.client.post('/account/documents/', {'kind': 'gst', 'file': png('a.png')}, **HX).status_code, 403)

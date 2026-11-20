from django.core.files.uploadedfile import SimpleUploadedFile

from sellers.models import SellerDocument

from .onboarding_helpers import HX, STEP1, OnboardingCase, pdf, png, step2_data, step2_files


class Step1Tests(OnboardingCase):
    def test_opens_at_step_one_and_saves_a_draft(self):
        r = self.client.get('/onboarding/', **HX)
        self.assertContains(r, 'Seller onboarding'); self.assertContains(r, 'Legal name')
        r = self.post_step(1, STEP1)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Step 1 saved'); self.assertContains(r, 'GST number')        # moved on to step 2
        self.me.refresh_from_db()
        self.assertEqual((self.me.legal_name, self.me.onboarding_step, self.me.status), ('Fresh Roots Pvt Ltd', 2, 'draft'))

    def test_close_and_resume_returns_to_the_saved_step(self):
        self.post_step(1, STEP1)
        self.assertContains(self.client.get('/onboarding/', **HX), 'GST number')
        self.assertContains(self.client.get('/onboarding/?step=1', **HX), 'Legal name')      # can go back and edit

    def test_cannot_jump_ahead_of_progress(self):
        self.assertContains(self.client.get('/onboarding/?step=4', **HX), 'Legal name')
        r = self.post_step(3, self.bank_data())
        self.assertEqual(r.status_code, 422)                                                 # treated as step 1, which is invalid
        self.me.refresh_from_db()
        self.assertFalse(hasattr(self.me, 'bank'))

    def test_validation(self):
        for change, text in (({'phone': '12345'}, 'valid 10-digit'), ({'year_established': '1850'}, 'between 1900'),
                             ({'business_type': ''}, 'required'), ({'legal_name': ''}, 'required')):
            r = self.post_step(1, {**STEP1, **change})
            self.assertContains(r, text, status_code=422)
        self.me.refresh_from_db(); self.assertEqual(self.me.legal_name, '')

    def test_logo_rules(self):
        too_big = SimpleUploadedFile('big.png', b'\x89PNG' + b'0' * (2 * 1024 * 1024 + 10), content_type='image/png')
        for bad, text in ((too_big, 'too large'), (SimpleUploadedFile('a.png', b'not an image'), 'PNG, JPG or SVG'),
                          (SimpleUploadedFile('a.svg', b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'), 'scripts')):
            self.assertContains(self.post_step(1, STEP1, {'logo': bad}), text, status_code=422)
        self.assertEqual(self.post_step(1, STEP1, {'logo': png('logo.png')}).status_code, 200)
        self.me.refresh_from_db(); self.assertTrue(self.me.logo.name.endswith('logo.png'))
        svg = SimpleUploadedFile('l.svg', b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><rect width="10" height="10"/></svg>')
        self.assertEqual(self.post_step(1, STEP1, {'logo': svg}).status_code, 200)

    def test_status_pages_lock_the_wizard_once_submitted(self):
        self.me.status = 'pending'; self.me.save()
        self.assertContains(self.client.get('/onboarding/', **HX), 'Application locked')
        self.assertEqual(self.post_step(1, STEP1).status_code, 403)


class Step2Tests(OnboardingCase):
    def setUp(self):
        super().setUp()
        self.post_step(1, STEP1)

    def test_valid_compliance_saves_numbers_and_documents(self):
        r = self.post_step(2, step2_data(), step2_files())
        self.assertEqual(r.status_code, 200); self.assertContains(r, 'Account holder')
        self.me.refresh_from_db()
        self.assertEqual((self.me.gst_number, self.me.pan_number, self.me.fssai_number, self.me.onboarding_step),
                         ('27ABCDE1234F1Z5', 'ABCDE1234F', '12345678901234', 3))
        self.assertEqual(self.me.gst_status, 'unverified')
        self.assertEqual(set(self.me.documents.values_list('kind', flat=True)), {'gst', 'pan', 'fssai'})
        self.assertIsNotNone(self.me.documents.get(kind='fssai').expires_on)

    def test_identifier_formats_are_checked(self):
        for change, text in (({'gst_number': '27ABCDE1234F1Z'}, 'valid 15-character GSTIN'), ({'pan_number': 'ABC12'}, 'valid 10-character PAN'),
                             ({'fssai_number': '123'}, '14 digits'), ({'fssai_expiry': '2020-01-01'}, 'must not be expired'),
                             ({'company_pan': 'bad'}, 'valid 10-character PAN')):
            self.assertContains(self.post_step(2, step2_data(**change), step2_files()), text, status_code=422)

    def test_required_documents(self):
        r = self.post_step(2, step2_data(), {})
        self.assertContains(r, 'Please upload this document', status_code=422)
        self.assertEqual(self.me.documents.count(), 0)

    def test_document_content_is_sniffed_not_trusted(self):
        fake = SimpleUploadedFile('gst.pdf', b'MZ this is an executable', content_type='application/pdf')
        self.assertContains(self.post_step(2, step2_data(), step2_files(doc_gst=fake)), 'photo (JPG/PNG) or a PDF', status_code=422)
        huge = SimpleUploadedFile('p.pdf', b'%PDF-' + b'0' * (5 * 1024 * 1024 + 5), content_type='application/pdf')
        self.assertContains(self.post_step(2, step2_data(), step2_files(doc_pan=huge)), 'too large', status_code=422)

    def test_camera_input_counts_as_a_document(self):
        files = step2_files(); del files['doc_gst']; files['doc_gst_camera'] = png('camera.jpg')
        self.assertEqual(self.post_step(2, step2_data(), files).status_code, 200)
        self.assertTrue(self.me.documents.filter(kind='gst').exists())

    def test_uploading_again_replaces_the_old_document_and_file(self):
        self.post_step(2, step2_data(), step2_files())
        old = self.me.documents.get(kind='gst'); old_path = old.file.path
        self.post_step(2, step2_data(), {'doc_gst': png('new.png')})                  # other required docs already on file
        self.assertEqual(self.me.documents.filter(kind='gst').count(), 1)
        import os
        self.assertFalse(os.path.exists(old_path))
        self.assertEqual(SellerDocument.objects.filter(seller=self.me).count(), 3)

    def test_changing_the_gstin_resets_verification(self):
        self.post_step(2, step2_data(), step2_files())
        type(self.me).objects.filter(pk=self.me.pk).update(gst_status='verified')
        self.post_step(2, step2_data(), {})
        self.me.refresh_from_db(); self.assertEqual(self.me.gst_status, 'verified')       # unchanged number keeps it
        self.post_step(2, step2_data(gst_number='29ABCDE1234F1Z5'), {})
        self.me.refresh_from_db(); self.assertEqual(self.me.gst_status, 'unverified')

import json
import os

from django.core.files.uploadedfile import SimpleUploadedFile

from catalog.models import APlusImage, Product, ProductImage

from .product_helpers import HX, ProductCase, png


class GalleryTests(ProductCase):
    def setUp(self):
        super().setUp()
        self.p = self.product()
        self.url = f'/products/{self.p.pk}/images/'

    def add(self, *files, text=''):
        return self.client.post(self.url + 'add/', {'files': list(files), 'text': text}, **HX)

    def test_add_several_images_with_order_and_description(self):
        r = self.add(png('a.png'), png('b.png'), png('c.png'), text='Front view')
        self.assertEqual(r.status_code, 204)
        trig = json.loads(r['HX-Trigger'])
        self.assertTrue(trig['gallery-changed']); self.assertIn('3 images added', trig['toast']['message'])
        imgs = list(self.p.images.all())
        self.assertEqual([i.sort_order for i in imgs], [0, 1, 2]); self.assertEqual(imgs[0].alt_text, 'Front view')

    def test_limit_of_eight(self):
        self.add(*[png(f'{i}.png') for i in range(7)])
        r = self.add(png('x.png'), png('y.png'))
        self.assertContains(r, 'You can add 1 more image', status_code=422)
        self.assertEqual(self.add(png('last.png')).status_code, 204)
        self.assertEqual(self.p.images.count(), 8)
        self.assertContains(self.client.get(self.url + 'add/', **HX), '0 more allowed')

    def test_files_are_checked_by_content_and_size(self):
        fake = SimpleUploadedFile('x.png', b'<html>not an image</html>', content_type='image/png')
        self.assertContains(self.add(fake), 'Upload a JPG, PNG or WebP', status_code=422)
        huge = SimpleUploadedFile('h.png', b'\x89PNG' + b'0' * (5 * 1024 * 1024 + 10), content_type='image/png')
        self.assertContains(self.add(huge), 'too large', status_code=422)
        self.assertContains(self.client.post(self.url + 'add/', {}, **HX), 'at least one image', status_code=422)
        self.assertEqual(self.p.images.count(), 0)

    def test_move_up_and_down_renumbers(self):
        self.add(png('a.png'), png('b.png'), png('c.png'))
        a, b, c = list(self.p.images.all())
        self.client.post(self.url + f'{c.pk}/move/up/', **HX)
        self.assertEqual([i.pk for i in self.p.images.all()], [a.pk, c.pk, b.pk])
        self.client.post(self.url + f'{a.pk}/move/up/', **HX)                    # already first: unchanged
        self.assertEqual([i.pk for i in self.p.images.all()], [a.pk, c.pk, b.pk])
        self.assertEqual(self.client.post(self.url + f'{a.pk}/move/sideways/', **HX).status_code, 404)

    def test_drag_reorder_must_name_exactly_this_products_images(self):
        self.add(png('a.png'), png('b.png'))
        a, b = list(self.p.images.all())
        self.assertEqual(self.client.post(self.url + 'reorder/', {'ids': f'{b.pk},{a.pk}'}, **HX).status_code, 204)
        self.assertEqual([i.pk for i in self.p.images.all()], [b.pk, a.pk])
        other = self.product(name='Other'); self.client.post(f'/products/{other.pk}/images/add/', {'files': [png('o.png')]}, **HX)
        foreign = other.images.get()
        for bad in (f'{a.pk}', f'{a.pk},{b.pk},{foreign.pk}', f'{a.pk},{foreign.pk}', 'x,y', ''):
            self.assertEqual(self.client.post(self.url + 'reorder/', {'ids': bad}, **HX).status_code, 400, bad)

    def test_delete_confirms_then_removes_row_and_file(self):
        self.add(png('a.png')); img = self.p.images.get(); path = img.image.path
        self.assertTrue(os.path.exists(path))
        self.assertContains(self.client.get(self.url + f'{img.pk}/delete/', **HX), 'The file is deleted')
        self.assertEqual(self.client.post(self.url + f'{img.pk}/delete/', **HX).status_code, 204)
        self.assertFalse(ProductImage.objects.exists()); self.assertFalse(os.path.exists(path))

    def test_alt_text_can_be_edited(self):
        self.add(png('a.png')); img = self.p.images.get()
        self.assertContains(self.client.get(self.url + f'{img.pk}/text/', **HX), 'Description')
        self.client.post(self.url + f'{img.pk}/text/', {'text': 'Side view'}, **HX)
        img.refresh_from_db(); self.assertEqual(img.alt_text, 'Side view')

    def test_list_partial_renders_with_empty_state(self):
        self.assertContains(self.client.get(self.url, **HX), 'No images yet')
        self.add(png('a.png'))
        r = self.client.get(self.url, **HX)
        self.assertContains(r, 'draggable="true"'); self.assertContains(r, '1 of 8 used')


class APlusTests(ProductCase):
    def setUp(self):
        super().setUp()
        self.p = self.product(); self.url = f'/products/{self.p.pk}/aplus/'

    def test_limit_of_five_with_captions(self):
        for i in range(5):
            self.assertEqual(self.client.post(self.url + 'add/', {'files': [png(f'{i}.png')], 'text': f'Cap {i}'}, **HX).status_code, 204)
        self.assertEqual([a.caption for a in self.p.aplus_images.all()], [f'Cap {i}' for i in range(5)])
        self.assertContains(self.client.post(self.url + 'add/', {'files': [png('x.png')]}, **HX), 'You can add 0 more', status_code=422)
        self.assertEqual(self.p.aplus_images.count(), 5)

    def test_aplus_uses_its_own_events_and_delete_url(self):
        r = self.client.post(self.url + 'add/', {'files': [png('a.png')]}, **HX)
        self.assertTrue(json.loads(r['HX-Trigger'])['aplus-changed'])
        item = self.p.aplus_images.get()
        self.assertContains(self.client.get(self.url + f'{item.pk}/delete/', **HX), f'/products/{self.p.pk}/aplus/{item.pk}/delete/')
        self.client.post(self.url + f'{item.pk}/delete/', **HX)
        self.assertFalse(APlusImage.objects.exists())


class MediaAccessTests(ProductCase):
    def setUp(self):
        super().setUp()
        self.theirs = self.product(seller=self.b, name='Theirs')
        self.client.logout(); self.login_as(self.b.user)
        self.client.post(f'/products/{self.theirs.pk}/images/add/', {'files': [png('t.png')]}, **HX)
        self.their_img = self.theirs.images.get()
        self.client.logout(); self.login_as(self.a.user)

    def test_other_sellers_media_is_404(self):
        base = f'/products/{self.theirs.pk}/images/'
        for method, url in (('get', base), ('get', base + 'add/'), ('post', base + 'add/'), ('post', base + 'reorder/'),
                            ('get', base + f'{self.their_img.pk}/text/'), ('post', base + f'{self.their_img.pk}/text/'),
                            ('get', base + f'{self.their_img.pk}/delete/'), ('post', base + f'{self.their_img.pk}/delete/'),
                            ('post', base + f'{self.their_img.pk}/move/up/'), ('get', f'/products/{self.theirs.pk}/aplus/')):
            self.assertEqual(getattr(self.client, method)(url, {'files': [png('z.png')], 'ids': '1', 'text': 'x'}, **HX).status_code, 404, f'{method} {url}')
        self.assertTrue(ProductImage.objects.filter(pk=self.their_img.pk).exists())

    def test_my_image_id_under_another_product_does_not_resolve(self):
        mine = self.product(name='Mine'); self.client.post(f'/products/{mine.pk}/images/add/', {'files': [png('m.png')]}, **HX)
        m = mine.images.get()
        self.assertEqual(self.client.post(f'/products/{self.theirs.pk}/images/{m.pk}/delete/', **HX).status_code, 404)
        other = self.product(name='Other')
        self.assertEqual(self.client.post(f'/products/{other.pk}/images/{m.pk}/delete/', **HX).status_code, 404)
        self.assertTrue(ProductImage.objects.filter(pk=m.pk).exists())

    def test_pending_products_lock_media_changes(self):
        mine = self.product(name='Mine'); self.client.post(f'/products/{mine.pk}/images/add/', {'files': [png('m.png')]}, **HX)
        img = mine.images.get(); Product.objects.filter(pk=mine.pk).update(status='pending')
        base = f'/products/{mine.pk}/images/'
        for method, url in (('get', base + 'add/'), ('post', base + 'add/'), ('post', base + f'{img.pk}/delete/'), ('post', base + 'reorder/'),
                            ('post', base + f'{img.pk}/move/down/'), ('post', base + f'{img.pk}/text/')):
            self.assertEqual(getattr(self.client, method)(url, {'files': [png('n.png')], 'ids': str(img.pk)}, **HX).status_code, 403, url)
        self.assertEqual(self.client.get(base, **HX).status_code, 200)            # reading is still fine
        self.assertEqual(mine.images.count(), 1)

    def test_unapproved_and_non_sellers_are_denied(self):
        mine = self.product(name='Mine')
        for user in (self.pending.user, self.customer):
            self.login_as(user)
            self.assertEqual(self.client.get(f'/products/{mine.pk}/images/add/', **HX).status_code, 403)

"""Forms for variants (price, stock, batch, expiry, tax and shipping package)."""
import re

from django import forms

from catalog.models import GST_RATES, ProductVariant

INPUT = {'class': 'input'}
NUM = {'class': 'input', 'inputmode': 'decimal'}
INT = {'class': 'input', 'inputmode': 'numeric'}
HSN_RE = re.compile(r'^\d{4}(\d{2})?(\d{2})?$')


class VariantForm(forms.ModelForm):
    class Meta:
        model = ProductVariant
        fields = ['label', 'sku', 'mrp', 'price', 'moq', 'stock', 'low_stock_threshold', 'batch_number', 'manufactured_on',
                  'expires_on', 'hsn_code', 'gst_rate', 'country_of_origin', 'dispatch_days',
                  'length_cm', 'width_cm', 'height_cm', 'weight_g']
        labels = {'label': 'Variant name', 'sku': 'SKU', 'mrp': 'MRP (₹)', 'price': 'Selling price (₹)', 'moq': 'Minimum order qty',
                  'stock': 'Stock', 'low_stock_threshold': 'Low-stock alert at', 'batch_number': 'Batch number',
                  'manufactured_on': 'Manufacture date', 'expires_on': 'Expiry date', 'hsn_code': 'HSN code', 'gst_rate': 'GST rate',
                  'country_of_origin': 'Country of origin', 'dispatch_days': 'Dispatch within (days)',
                  'length_cm': 'Length (cm)', 'width_cm': 'Width (cm)', 'height_cm': 'Height (cm)', 'weight_g': 'Dead weight (g)'}
        widgets = {
            'label': forms.TextInput(attrs={**INPUT, 'placeholder': 'e.g. 1 kg Chocolate'}),
            'sku': forms.TextInput(attrs={**INPUT, 'autocapitalize': 'characters'}),
            'mrp': forms.NumberInput(attrs={**NUM, 'step': '0.01', 'min': '0'}),
            'price': forms.NumberInput(attrs={**NUM, 'step': '0.01', 'min': '0'}),
            'moq': forms.NumberInput(attrs={**INT, 'min': '1'}), 'stock': forms.NumberInput(attrs={**INT, 'min': '0'}),
            'low_stock_threshold': forms.NumberInput(attrs={**INT, 'min': '0'}),
            'batch_number': forms.TextInput(attrs=INPUT),
            'manufactured_on': forms.DateInput(attrs={**INPUT, 'type': 'date'}),
            'expires_on': forms.DateInput(attrs={**INPUT, 'type': 'date'}),
            'hsn_code': forms.TextInput(attrs={**INT, 'maxlength': 8}),
            'gst_rate': forms.Select(attrs={'class': 'select'}, choices=GST_RATES),
            'country_of_origin': forms.TextInput(attrs=INPUT),
            'dispatch_days': forms.NumberInput(attrs={**INT, 'min': '0', 'max': '30'}),
            'length_cm': forms.NumberInput(attrs={**NUM, 'step': '0.1', 'min': '0', 'data-w': 'l'}),
            'width_cm': forms.NumberInput(attrs={**NUM, 'step': '0.1', 'min': '0', 'data-w': 'w'}),
            'height_cm': forms.NumberInput(attrs={**NUM, 'step': '0.1', 'min': '0', 'data-w': 'h'}),
            'weight_g': forms.NumberInput(attrs={**INT, 'min': '0', 'data-w': 'g'}),
        }

    def __init__(self, *args, seller, product, **kwargs):
        kwargs.setdefault('instance', ProductVariant(product=product, seller=seller))
        super().__init__(*args, **kwargs)
        self.seller, self.product = seller, product
        for name in ('label', 'sku', 'mrp', 'price', 'gst_rate'):
            self.fields[name].required = True
        self.fields['moq'].min_value = 1
        if not self.instance.pk:
            self.fields['gst_rate'].initial = product.subcategory.default_gst_rate
            self.fields['dispatch_days'].initial = seller.dispatch_days
        self.fields['gst_rate'].help_text = 'Standard slabs only: 0, 5, 12 or 18%.'

    def clean_sku(self):
        sku = self.cleaned_data['sku'].strip().upper()
        dup = ProductVariant.objects.filter(seller=self.seller, sku=sku)
        if self.instance.pk:
            dup = dup.exclude(pk=self.instance.pk)
        if dup.exists():
            raise forms.ValidationError('You already use this SKU on another variant.')
        return sku

    def _positive(self, name):
        v = self.cleaned_data[name]
        if v is None or v <= 0:
            raise forms.ValidationError('Enter an amount greater than zero.')
        return v

    def clean_mrp(self):
        return self._positive('mrp')

    def clean_price(self):
        return self._positive('price')

    def clean_hsn_code(self):
        v = (self.cleaned_data.get('hsn_code') or '').strip()
        if v and not HSN_RE.match(v):
            raise forms.ValidationError('HSN code must be 4, 6 or 8 digits.')
        return v

    def clean_moq(self):
        v = self.cleaned_data['moq']
        if v < 1:
            raise forms.ValidationError('Minimum order quantity is at least 1.')
        return v

    def clean(self):
        cleaned = super().clean()
        dims = [cleaned.get(k) for k in ('length_cm', 'width_cm', 'height_cm')]
        if any(dims) and not all(dims):
            self.add_error(None, 'Enter all three dimensions (length, width, height) or leave them all blank.')
        return cleaned


class BulkSizesForm(forms.Form):
    sizes = forms.CharField(
        label='Sizes', widget=forms.Textarea(attrs={'class': 'textarea', 'rows': 4, 'placeholder': '250 g\n500 g\n1 kg'}),
        help_text='One per line, or separated by commas. Up to 12. You will fill in price and stock for each next.')

    def clean_sizes(self):
        parts = [p.strip() for p in re.split(r'[\n,;]+', self.cleaned_data['sizes']) if p.strip()]
        seen, out = set(), []
        for p in parts:
            if p.lower() not in seen:
                seen.add(p.lower()); out.append(p)
        if not out:
            raise forms.ValidationError('Enter at least one size.')
        if len(out) > 12:
            raise forms.ValidationError('Add up to 12 sizes at a time.')
        if any(len(p) > 80 for p in out):
            raise forms.ValidationError('Each size must be 80 characters or fewer.')
        return out

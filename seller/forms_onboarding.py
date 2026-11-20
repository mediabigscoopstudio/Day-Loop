"""Onboarding wizard forms (steps 1-3; step 4 is the review + agreement)."""
from datetime import date

from django import forms
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import UploadedFile

from catalog.models import Category
from sellers import validators as v
from sellers.models import SellerDocument, SellerProfile

from .uploads import validate_document, validate_logo

INPUT = {'class': 'input'}
CAMERA_SUFFIX = '_camera'


class FileCameraMixin:
    """
    Every file field `x` gets a companion `x_camera` input (capture="environment") so phones can
    take a photo directly, while `x` still offers the gallery / file picker. Whichever is filled wins.
    """

    file_fields = ()

    def _add_camera_fields(self):
        for name in self.file_fields:
            self.fields[name + CAMERA_SUFFIX] = forms.FileField(
                required=False, widget=forms.FileInput(attrs={'accept': 'image/*', 'capture': 'environment', 'class': 'sr-only'}))

    def picked_file(self, name):
        return self.cleaned_data.get(name) or self.cleaned_data.get(name + CAMERA_SUFFIX)


class BusinessForm(FileCameraMixin, forms.ModelForm):
    file_fields = ()
    # A plain FileField (not ImageField): Pillow cannot read SVG, and validate_logo does real content checks.
    logo = forms.FileField(required=False, widget=forms.FileInput(
        attrs={'accept': 'image/png,image/jpeg,image/svg+xml', 'data-preview': 'square'}))

    class Meta:
        model = SellerProfile
        fields = ['legal_name', 'business_name', 'business_type', 'logo', 'contact_person', 'phone', 'email',
                  'address', 'city', 'year_established']
        labels = {'business_name': 'Trade name', 'legal_name': 'Legal name', 'address': 'Registered address',
                  'year_established': 'Year established'}
        widgets = {
            'legal_name': forms.TextInput(attrs=INPUT), 'business_name': forms.TextInput(attrs=INPUT),
            'business_type': forms.Select(attrs={'class': 'select'}),
            'contact_person': forms.TextInput(attrs=INPUT),
            'phone': forms.TextInput(attrs={**INPUT, 'inputmode': 'tel', 'autocomplete': 'tel'}),
            'email': forms.EmailInput(attrs={**INPUT, 'inputmode': 'email'}),
            'address': forms.Textarea(attrs={'class': 'textarea', 'rows': 3}),
            'city': forms.TextInput(attrs=INPUT),
            'year_established': forms.NumberInput(attrs={**INPUT, 'inputmode': 'numeric', 'min': 1900, 'max': date.today().year}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ('legal_name', 'business_name', 'business_type', 'contact_person', 'phone', 'email', 'address'):
            self.fields[name].required = True
        self.fields['business_type'].choices = [('', 'Select…')] + list(SellerProfile.BusinessType.choices)
        self.fields['logo'].required = False
        self.fields['logo'].help_text = 'PNG, JPG or SVG, up to 2 MB. Shown as a square.'

    def clean_logo(self):
        logo = self.cleaned_data.get('logo')
        if isinstance(logo, UploadedFile):          # only validate a fresh upload, not the stored file
            validate_logo(logo)
        return logo

    def clean_phone(self):
        return v.validate_phone(self.cleaned_data['phone'])

    def clean_year_established(self):
        y = self.cleaned_data.get('year_established')
        if y is not None and not (1900 <= y <= date.today().year):
            raise ValidationError(f'Enter a year between 1900 and {date.today().year}.')
        return y


DOC_FIELDS = [
    ('doc_gst', SellerDocument.Kind.GST, True), ('doc_pan', SellerDocument.Kind.PAN, True),
    ('doc_company_pan', SellerDocument.Kind.COMPANY_PAN, False), ('doc_fssai', SellerDocument.Kind.FSSAI, True),
    ('doc_mfg_licence', SellerDocument.Kind.MFG, False), ('doc_gmp', SellerDocument.Kind.GMP, False),
    ('doc_iso22000', SellerDocument.Kind.ISO, False), ('doc_haccp', SellerDocument.Kind.HACCP, False),
]


class ComplianceForm(FileCameraMixin, forms.Form):
    gst_number = forms.CharField(label='GST number (GSTIN)', max_length=15, widget=forms.TextInput(attrs={**INPUT, 'autocapitalize': 'characters'}))
    pan_number = forms.CharField(label='PAN', max_length=10, widget=forms.TextInput(attrs={**INPUT, 'autocapitalize': 'characters'}))
    company_pan = forms.CharField(label='Company PAN', max_length=10, required=False, widget=forms.TextInput(attrs={**INPUT, 'autocapitalize': 'characters'}))
    fssai_number = forms.CharField(label='FSSAI licence number', max_length=14, widget=forms.TextInput(attrs={**INPUT, 'inputmode': 'numeric'}))
    fssai_expiry = forms.DateField(label='FSSAI expiry date', widget=forms.DateInput(attrs={**INPUT, 'type': 'date'}))
    mfg_licence_number = forms.CharField(label='Manufacturing licence number', max_length=60, required=False, widget=forms.TextInput(attrs=INPUT))
    doc_gst = forms.FileField(label='GST certificate', required=False)
    doc_pan = forms.FileField(label='PAN card', required=False)
    doc_company_pan = forms.FileField(label='Company PAN card', required=False)
    doc_fssai = forms.FileField(label='FSSAI licence', required=False)
    doc_mfg_licence = forms.FileField(label='Manufacturing licence', required=False)
    doc_gmp = forms.FileField(label='GMP certificate', required=False)
    doc_iso22000 = forms.FileField(label='ISO 22000 certificate', required=False)
    doc_haccp = forms.FileField(label='HACCP certificate', required=False)
    file_fields = tuple(n for n, _, _ in DOC_FIELDS)

    def __init__(self, *args, seller=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.seller = seller
        self._add_camera_fields()
        self.have = set(seller.documents.values_list('kind', flat=True)) if seller else set()
        for name, kind, _ in DOC_FIELDS:
            self.fields[name].widget = forms.FileInput(attrs={'accept': 'image/*,application/pdf', 'data-doc': '1'})

    def clean_gst_number(self):
        return v.validate_gst(self.cleaned_data['gst_number'])

    def clean_pan_number(self):
        return v.validate_pan(self.cleaned_data['pan_number'])

    def clean_company_pan(self):
        val = self.cleaned_data.get('company_pan', '')
        return v.validate_pan(val) if val else ''

    def clean_fssai_number(self):
        return v.validate_fssai(self.cleaned_data['fssai_number'])

    def clean_fssai_expiry(self):
        d = self.cleaned_data['fssai_expiry']
        if d <= date.today():
            raise ValidationError('Your FSSAI licence must not be expired.')
        return d

    def clean(self):
        cleaned = super().clean()
        for name, kind, required in DOC_FIELDS:
            f = self.picked_file(name) if hasattr(self, 'cleaned_data') else None
            if f:
                try:
                    validate_document(f)
                except ValidationError as e:
                    self.add_error(name, e)
            elif required and kind not in self.have:
                self.add_error(name, 'Please upload this document.')
        return cleaned


class BankOpsForm(FileCameraMixin, forms.Form):
    account_holder = forms.CharField(max_length=120, widget=forms.TextInput(attrs=INPUT))
    account_number = forms.CharField(max_length=24, required=False, widget=forms.TextInput(attrs={**INPUT, 'inputmode': 'numeric', 'autocomplete': 'off'}))
    ifsc = forms.CharField(label='IFSC', max_length=11, widget=forms.TextInput(attrs={**INPUT, 'autocapitalize': 'characters'}))
    bank_name = forms.CharField(max_length=80, widget=forms.TextInput(attrs=INPUT))
    upi_id = forms.CharField(label='UPI ID (optional)', max_length=80, required=False, widget=forms.TextInput(attrs={**INPUT, 'inputmode': 'email'}))
    categories = forms.ModelMultipleChoiceField(
        label='Product categories you sell', queryset=Category.objects.none(), widget=forms.CheckboxSelectMultiple,
        help_text='Managed by Day Loop. Pick every category you sell in.')
    dispatch_days = forms.IntegerField(label='Typical dispatch time (days)', min_value=1, max_value=15, initial=2,
                                       widget=forms.NumberInput(attrs={**INPUT, 'inputmode': 'numeric'}))
    dispatch_address = forms.CharField(label='Dispatch address (if different)', required=False,
                                       widget=forms.Textarea(attrs={'class': 'textarea', 'rows': 2}))
    doc_cheque = forms.FileField(label='Cancelled cheque (optional)', required=False,
                                 widget=forms.FileInput(attrs={'accept': 'image/*,application/pdf', 'data-doc': '1'}))
    file_fields = ('doc_cheque',)

    def __init__(self, *args, seller=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.seller = seller
        self._add_camera_fields()
        self.fields['categories'].queryset = Category.objects.filter(parent__isnull=True, is_active=True)
        self.has_bank = bool(seller and hasattr(seller, 'bank'))
        if self.has_bank:      # shown masked; leaving it blank keeps the saved number
            self.fields['account_number'].help_text = f'Saved: {seller.bank.masked_number}. Leave blank to keep it.'
        else:
            self.fields['account_number'].required = True

    def clean_account_number(self):
        val = self.cleaned_data.get('account_number', '')
        if not val and self.has_bank:
            return ''
        return v.validate_account_number(val)

    def clean_ifsc(self):
        return v.validate_ifsc(self.cleaned_data['ifsc'])

    def clean_upi_id(self):
        return v.validate_upi(self.cleaned_data.get('upi_id', ''))

    def clean(self):
        cleaned = super().clean()
        f = self.picked_file('doc_cheque')
        if f:
            try:
                validate_document(f)
            except ValidationError as e:
                self.add_error('doc_cheque', e)
        return cleaned


class ReviewForm(forms.Form):
    accept_commission = forms.BooleanField(
        label='I agree to the Day Loop seller agreement: a 5% platform commission on each order, plus 18% GST on that commission.',
        error_messages={'required': 'Please accept the commission agreement to submit.'})

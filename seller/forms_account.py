"""Account popups: profile + logo, bank details (re-verification), password and document replacement."""
from datetime import date

from django import forms
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import UploadedFile

from sellers import validators as v
from sellers.models import SellerDocument, SellerProfile

from .uploads import validate_document, validate_logo

INPUT = {'class': 'input'}


class ProfileForm(forms.ModelForm):
    """Contact details and logo. Legal name, business type and compliance IDs change through support."""

    logo = forms.FileField(required=False, widget=forms.FileInput(
        attrs={'accept': 'image/png,image/jpeg,image/svg+xml', 'data-preview': 'square'}))

    class Meta:
        model = SellerProfile
        fields = ['business_name', 'contact_person', 'phone', 'email', 'address', 'city', 'logo']
        labels = {'business_name': 'Trade name', 'address': 'Registered address'}
        widgets = {
            'business_name': forms.TextInput(attrs=INPUT), 'contact_person': forms.TextInput(attrs=INPUT),
            'phone': forms.TextInput(attrs={**INPUT, 'inputmode': 'tel'}), 'email': forms.EmailInput(attrs={**INPUT, 'inputmode': 'email'}),
            'address': forms.Textarea(attrs={'class': 'textarea', 'rows': 3}), 'city': forms.TextInput(attrs=INPUT),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for n in ('business_name', 'contact_person', 'phone', 'email', 'address'):
            self.fields[n].required = True
        self.fields['logo'].help_text = 'PNG, JPG or SVG, up to 2 MB. Shown as a square.'

    def clean_phone(self):
        return v.validate_phone(self.cleaned_data['phone'])

    def clean_logo(self):
        logo = self.cleaned_data.get('logo')
        if isinstance(logo, UploadedFile):
            validate_logo(logo)
        return logo


class _PasswordCheck(forms.Form):
    current_password = forms.CharField(strip=False, widget=forms.PasswordInput(attrs={**INPUT, 'autocomplete': 'current-password'}))

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean_current_password(self):
        pw = self.cleaned_data['current_password']
        if not self.user.check_password(pw):
            raise ValidationError('That password is not correct.')
        return pw


class BankEditForm(_PasswordCheck):
    account_holder = forms.CharField(max_length=120, widget=forms.TextInput(attrs=INPUT))
    account_number = forms.CharField(max_length=24, required=False, widget=forms.TextInput(attrs={**INPUT, 'inputmode': 'numeric', 'autocomplete': 'off'}))
    ifsc = forms.CharField(label='IFSC', max_length=11, widget=forms.TextInput(attrs={**INPUT, 'autocapitalize': 'characters'}))
    bank_name = forms.CharField(max_length=80, widget=forms.TextInput(attrs=INPUT))
    upi_id = forms.CharField(label='UPI ID (optional)', max_length=80, required=False, widget=forms.TextInput(attrs=INPUT))
    field_order = ['account_holder', 'account_number', 'ifsc', 'bank_name', 'upi_id', 'current_password']

    def __init__(self, *args, bank=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.bank = bank
        if bank:
            self.fields['account_number'].help_text = f'Saved: {bank.masked_number}. Leave blank to keep it.'
        else:
            self.fields['account_number'].required = True
        self.fields['current_password'].help_text = 'Confirm your password to change bank details.'

    def clean_account_number(self):
        val = self.cleaned_data.get('account_number', '')
        return v.validate_account_number(val) if val else ''

    def clean_ifsc(self):
        return v.validate_ifsc(self.cleaned_data['ifsc'])

    def clean_upi_id(self):
        return v.validate_upi(self.cleaned_data.get('upi_id', ''))


class PasswordChangeForm(_PasswordCheck):
    new_password = forms.CharField(strip=False, widget=forms.PasswordInput(attrs={**INPUT, 'autocomplete': 'new-password'}))
    confirm_password = forms.CharField(strip=False, widget=forms.PasswordInput(attrs={**INPUT, 'autocomplete': 'new-password'}))

    def clean(self):
        c = super().clean()
        new, conf = c.get('new_password'), c.get('confirm_password')
        if new and new != conf:
            self.add_error('confirm_password', 'The two passwords do not match.')
        elif new:
            try:
                validate_password(new, self.user)
            except ValidationError as e:
                self.add_error('new_password', e)
            if c.get('current_password') and new == c.get('current_password'):
                self.add_error('new_password', 'Choose a password different from your current one.')
        return c


REPLACEABLE = [k for k in SellerDocument.Kind]


class DocumentReplaceForm(forms.Form):
    kind = forms.ChoiceField(choices=[(k.value, k.label) for k in REPLACEABLE], widget=forms.Select(attrs={'class': 'select'}))
    file = forms.FileField(widget=forms.FileInput(attrs={'accept': 'image/*,application/pdf', 'data-doc': '1'}))
    expires_on = forms.DateField(required=False, label='Expiry date (if any)', widget=forms.DateInput(attrs={**INPUT, 'type': 'date'}))

    def clean_file(self):
        f = self.cleaned_data['file']
        validate_document(f)
        return f

    def clean_expires_on(self):
        d = self.cleaned_data.get('expires_on')
        if d and d <= date.today():
            raise ValidationError('The expiry date must be in the future.')
        return d

    def clean(self):
        c = super().clean()
        if c.get('kind') == SellerDocument.Kind.FSSAI and not c.get('expires_on'):
            self.add_error('expires_on', 'An FSSAI licence needs its expiry date.')
        return c

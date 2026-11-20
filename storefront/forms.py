import re

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password

from .models import Address, Subscription

User = get_user_model()


class StyledForm(forms.Form):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        for f in self.fields.values():
            if not isinstance(f.widget, (forms.CheckboxInput, forms.RadioSelect)):
                f.widget.attrs.setdefault('class', 'input')


class LoginForm(StyledForm):
    identifier = forms.CharField(label='Email or username')
    password = forms.CharField(widget=forms.PasswordInput, strip=False)


class SignupForm(StyledForm):
    name = forms.CharField(max_length=100)
    email = forms.EmailField()
    password = forms.CharField(widget=forms.PasswordInput, strip=False, min_length=8)

    def clean_email(self):
        e = self.cleaned_data['email'].strip().lower()
        if User.objects.filter(email__iexact=e).exists() or User.objects.filter(username__iexact=e).exists():
            raise forms.ValidationError('An account with this email already exists. Sign in instead.')
        return e

    def clean_password(self):
        validate_password(self.cleaned_data['password'])
        return self.cleaned_data['password']


class AddressForm(forms.ModelForm):
    class Meta:
        model = Address
        fields = ['name', 'phone', 'line1', 'area', 'city', 'state', 'pincode', 'is_default']

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        for f in self.fields.values():
            if not isinstance(f.widget, forms.CheckboxInput):
                f.widget.attrs['class'] = 'input'

    def clean_pincode(self):
        p = self.cleaned_data['pincode'].strip()
        if not re.fullmatch(r'\d{6}', p):
            raise forms.ValidationError('Enter a 6-digit pincode.')
        return p

    def clean_phone(self):
        p = self.cleaned_data['phone'].strip()
        if p and not re.fullmatch(r'[+\d][\d\s-]{8,14}', p):
            raise forms.ValidationError('Enter a valid phone number.')
        return p


class ProfileForm(StyledForm):
    first_name = forms.CharField(max_length=150)
    last_name = forms.CharField(max_length=150, required=False)
    email = forms.EmailField()


class PasswordForm(StyledForm):
    current = forms.CharField(widget=forms.PasswordInput, strip=False, label='Current password')
    new = forms.CharField(widget=forms.PasswordInput, strip=False, label='New password')

    def clean_new(self):
        validate_password(self.cleaned_data['new'])
        return self.cleaned_data['new']


class FrequencyForm(StyledForm):
    frequency_days = forms.ChoiceField(choices=[(15, 'Every 15 days'), (30, 'Every 30 days'), (45, 'Every 45 days'), (60, 'Every 60 days')],
                                       label='Deliver')


class ScheduleForm(StyledForm):
    date = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}))
    slot = forms.ChoiceField(choices=[('morning', 'Morning 8am – 12pm'), ('afternoon', 'Afternoon 12pm – 4pm'), ('evening', 'Evening 4pm – 8pm')])

    def clean_date(self):
        from datetime import date
        d = self.cleaned_data['date']
        if d < date.today():
            raise forms.ValidationError('Pick today or a later date.')
        return d

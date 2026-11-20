"""Indian business-identifier validators used by the onboarding forms."""
import re

from django.core.exceptions import ValidationError

GST_RE = re.compile(r'^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$')
PAN_RE = re.compile(r'^[A-Z]{5}\d{4}[A-Z]$')
IFSC_RE = re.compile(r'^[A-Z]{4}0[A-Z0-9]{6}$')
FSSAI_RE = re.compile(r'^\d{14}$')
PHONE_RE = re.compile(r'^(\+91[\-\s]?)?[6-9]\d{9}$')
ACCOUNT_RE = re.compile(r'^\d{9,18}$')
UPI_RE = re.compile(r'^[\w.\-]{2,256}@[a-zA-Z]{2,64}$')


def _check(pattern, value, message):
    v = (value or '').strip().upper()
    if not pattern.match(v):
        raise ValidationError(message)
    return v


def validate_gst(value):
    return _check(GST_RE, value, 'Enter a valid 15-character GSTIN, e.g. 27ABCDE1234F1Z5.')


def validate_pan(value):
    return _check(PAN_RE, value, 'Enter a valid 10-character PAN, e.g. ABCDE1234F.')


def validate_ifsc(value):
    return _check(IFSC_RE, value, 'Enter a valid 11-character IFSC, e.g. HDFC0001234.')


def validate_fssai(value):
    return _check(FSSAI_RE, (value or '').replace(' ', ''), 'FSSAI licence number must be 14 digits.')


def validate_phone(value):
    v = (value or '').strip()
    if not PHONE_RE.match(v):
        raise ValidationError('Enter a valid 10-digit Indian mobile number.')
    return v


def validate_account_number(value):
    v = (value or '').replace(' ', '')
    if not ACCOUNT_RE.match(v):
        raise ValidationError('Account number must be 9 to 18 digits.')
    return v


def validate_upi(value):
    v = (value or '').strip()
    if v and not UPI_RE.match(v):
        raise ValidationError('Enter a valid UPI ID, e.g. name@bank.')
    return v


def mask_account(number: str) -> str:
    n = (number or '').replace(' ', '')
    return ('•' * max(len(n) - 4, 0)) + n[-4:] if n else ''

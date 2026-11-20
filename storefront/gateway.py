"""Mock payment gateway. Simulates a hosted payment; no network, no real money."""
import uuid
from dataclasses import dataclass

METHODS = [('upi', 'UPI'), ('card', 'Cards'), ('netbanking', 'Net banking'), ('cod', 'Cash on delivery')]
METHOD_LABELS = dict(METHODS)


@dataclass
class PaymentResult:
    ok: bool
    reference: str
    message: str


def charge(amount, method, simulate='success'):
    """simulate: 'success' | 'failure' (the popup lets the customer choose)."""
    if method not in METHOD_LABELS:
        return PaymentResult(False, '', 'Choose a valid payment method.')
    ref = f'MOCK-{uuid.uuid4().hex[:12].upper()}'
    if method == 'cod':
        return PaymentResult(True, ref, 'Pay on delivery.')
    if simulate == 'failure':
        return PaymentResult(False, ref, 'The bank declined the payment.')
    return PaymentResult(True, ref, 'Payment received.')

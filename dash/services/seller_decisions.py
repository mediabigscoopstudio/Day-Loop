"""Approve / reject / request-info decisions on seller applications."""
from django.db import transaction
from django.utils import timezone

from sellers.models import SellerProfile, SellerStatusHistory

S = SellerProfile.Status

ACTIONS = {
    'approve': {'to': S.APPROVED, 'reason_required': False, 'verb': 'approved'},
    'reject': {'to': S.REJECTED, 'reason_required': True, 'verb': 'rejected'},
    'request-info': {'to': S.NEEDS_INFO, 'reason_required': True, 'verb': 'sent a request for more information'},
}


class DecisionError(Exception):
    """Raised for a rule violation; message is safe to show in the popup."""


def allowed_actions(seller):
    """Which decisions make sense from the current status (never the same status twice)."""
    return [a for a, cfg in ACTIONS.items() if cfg['to'] != seller.status]


@transaction.atomic
def decide(seller_id, action, actor, reason=''):
    cfg = ACTIONS.get(action)
    if cfg is None:
        raise DecisionError('Unknown action.')
    seller = SellerProfile.objects.select_for_update().get(pk=seller_id)
    reason = (reason or '').strip()
    if cfg['reason_required'] and not reason:
        raise DecisionError('A reason is required.')
    if seller.status == cfg['to']:
        raise DecisionError(f'This seller is already {seller.get_status_display().lower()}.')
    SellerStatusHistory.objects.create(
        seller=seller, from_status=seller.status, to_status=cfg['to'], reason=reason, actor=actor,
    )
    seller.status = cfg['to']
    seller.decided_at = timezone.now()
    seller.save(update_fields=['status', 'decided_at'])
    return seller

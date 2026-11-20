"""Small helpers for HTMX responses (success = 204 + HX-Trigger events)."""
import json

from django.http import HttpResponse


def trigger_response(message=None, level='success', events=(), close=True):
    """204 response that closes the modal, shows a toast and fires refresh events."""
    payload = {}
    if close:
        payload['closeModal'] = True
    if message:
        payload['toast'] = {'message': message, 'level': level}
    for e in events:
        payload[e] = True
    return HttpResponse(status=204, headers={'HX-Trigger': json.dumps(payload)})

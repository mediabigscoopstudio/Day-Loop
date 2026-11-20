"""Delivery tiers. Config-driven: edit SERVICEABLE_AREAS / CITY_DEFAULTS, nothing else."""
from datetime import date, timedelta

FASTEST, SAME_DAY, SCHEDULED = 'fastest', 'same_day', 'scheduled'

TIER_LABELS = {FASTEST: '15 min delivery', SAME_DAY: 'Same day', SCHEDULED: 'Scheduled'}
OPTION_LABELS = {FASTEST: 'Fastest · 15 min', SAME_DAY: 'Same day', SCHEDULED: 'Scheduled'}

# (area, city) -> best tier available there
SERVICEABLE_AREAS = [
    {'area': 'Indiranagar', 'city': 'Bengaluru', 'tier': FASTEST},
    {'area': 'Koramangala', 'city': 'Bengaluru', 'tier': SAME_DAY},
    {'area': 'HSR Layout', 'city': 'Bengaluru', 'tier': SAME_DAY},
    {'area': 'Whitefield', 'city': 'Bengaluru', 'tier': SAME_DAY},
    {'area': 'Jayanagar', 'city': 'Bengaluru', 'tier': SAME_DAY},
    {'area': 'Bandra', 'city': 'Mumbai', 'tier': SCHEDULED},
    {'area': 'Connaught Place', 'city': 'Delhi', 'tier': SCHEDULED},
    {'area': 'Banjara Hills', 'city': 'Hyderabad', 'tier': SCHEDULED},
]
CITY_DEFAULTS = {'bengaluru': SAME_DAY}
DEFAULT_TIER = SCHEDULED
DEFAULT_AREA = SERVICEABLE_AREAS[0]

# which options each tier makes available
TIER_OPTIONS = {
    FASTEST: [FASTEST, SAME_DAY, SCHEDULED],
    SAME_DAY: [SAME_DAY, SCHEDULED],
    SCHEDULED: [SCHEDULED],
}
UNAVAILABLE_REASON = {
    FASTEST: 'Not available in your area yet',
    SAME_DAY: 'Not available in your city yet',
}


def find_area(area, city=''):
    for a in SERVICEABLE_AREAS:
        if a['area'].lower() == (area or '').lower() and (not city or a['city'].lower() == city.lower()):
            return a
    return None


def tier_for(area, city=''):
    a = find_area(area, city)
    if a:
        return a['tier']
    return CITY_DEFAULTS.get((city or '').strip().lower(), DEFAULT_TIER)


def search_areas(q):
    q = (q or '').strip().lower()
    return [a for a in SERVICEABLE_AREAS if not q or q in a['area'].lower() or q in a['city'].lower()]


def options_for(tier):
    avail = TIER_OPTIONS.get(tier, TIER_OPTIONS[SCHEDULED])
    return [{'key': k, 'label': OPTION_LABELS[k], 'available': k in avail,
             'reason': '' if k in avail else UNAVAILABLE_REASON.get(k, '')}
            for k in (FASTEST, SAME_DAY, SCHEDULED)]


def eta_for(tier, dispatch_days=0, today=None):
    """Human ETA for a shipment from the tier and the seller's dispatch days."""
    today = today or date.today()
    dispatch_days = int(dispatch_days or 0)
    if tier == FASTEST and dispatch_days <= 0:
        return 'Within 15 min'
    if tier == SAME_DAY and dispatch_days <= 0:
        return 'Today'
    extra = {FASTEST: 0, SAME_DAY: 1, SCHEDULED: 2}.get(tier, 2)
    d = today + timedelta(days=max(dispatch_days, 0) + extra)
    return d.strftime('%a, %d %b')


def session_area(request):
    s = request.session
    return {'area': s.get('area', DEFAULT_AREA['area']), 'city': s.get('city', DEFAULT_AREA['city'])}


def session_tier(request):
    a = session_area(request)
    return tier_for(a['area'], a['city'])

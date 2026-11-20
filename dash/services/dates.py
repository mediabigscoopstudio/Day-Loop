"""Date-range handling for dashboards: presets, custom ranges and the prior period."""
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from django.utils import timezone

PRESETS = [
    ('today', 'Today'), ('7d', '7D'), ('30d', '30D'), ('90d', '90D'), ('12m', '12M'), ('custom', 'Custom'),
]
PRESET_DAYS = {'today': 1, '7d': 7, '30d': 30, '90d': 90, '12m': 365}
DEFAULT_PRESET = '30d'
MAX_DAYS = 800


@dataclass(frozen=True)
class DateRange:
    start: datetime   # inclusive, aware
    end: datetime     # exclusive, aware
    preset: str
    start_date: date
    end_date: date    # inclusive, for display

    @property
    def days(self):
        return (self.end - self.start).days

    @property
    def prior(self):
        """The previous period of equal length, ending where this one starts."""
        length = self.end - self.start
        return DateRange(
            start=self.start - length, end=self.start, preset=self.preset,
            start_date=(self.start - length).date(),
            end_date=(self.start - timedelta(days=1)).date(),
        )

    @property
    def granularity(self):
        return 'day' if self.days <= 92 else 'month'

    def label(self):
        if self.start_date == self.end_date:
            return self.start_date.strftime('%b %-d, %Y')
        return f"{self.start_date.strftime('%b %-d, %Y')} – {self.end_date.strftime('%b %-d, %Y')}"

    def query_string(self):
        if self.preset == 'custom':
            return f'range=custom&start={self.start_date.isoformat()}&end={self.end_date.isoformat()}'
        return f'range={self.preset}'


def _aware_midnight(d: date) -> datetime:
    return timezone.make_aware(datetime.combine(d, datetime.min.time()))


def build_range(start_date: date, end_date: date, preset='custom') -> DateRange:
    """end_date is inclusive; the stored end is the next midnight (exclusive)."""
    return DateRange(
        start=_aware_midnight(start_date),
        end=_aware_midnight(end_date + timedelta(days=1)),
        preset=preset, start_date=start_date, end_date=end_date,
    )


def parse_range(params, today: date | None = None) -> DateRange:
    """Build a DateRange from request.GET. Invalid input falls back to the default preset."""
    today = today or timezone.localdate()
    preset = params.get('range', DEFAULT_PRESET)
    if preset == 'custom':
        try:
            s = date.fromisoformat(params.get('start', ''))
            e = date.fromisoformat(params.get('end', ''))
        except ValueError:
            s = e = None
        if s and e and s <= e and (e - s).days < MAX_DAYS:
            return build_range(s, e, 'custom')
        preset = DEFAULT_PRESET
    if preset not in PRESET_DAYS:
        preset = DEFAULT_PRESET
    days = PRESET_DAYS[preset]
    return build_range(today - timedelta(days=days - 1), today, preset)


def delta_pct(current, prior):
    """Percent change vs prior. None when prior is 0 and current is not (no baseline)."""
    current, prior = float(current or 0), float(prior or 0)
    if prior == 0:
        return 0.0 if current == 0 else None
    return round((current - prior) / prior * 100, 1)

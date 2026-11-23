"""Display and edit wall-clock schedule times in the simulator's own zone."""
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from django import forms
from django.utils import timezone


def schedule_zone(name):
    try:
        return ZoneInfo(name or 'UTC')
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo('UTC')


def local_schedule_time(value, zone):
    if value is None:
        return None
    if timezone.is_naive(value):
        value = timezone.make_aware(value, ZoneInfo('UTC'))
    return timezone.localtime(value, zone)


def display_schedule_time(value, zone):
    local = local_schedule_time(value, zone)
    if local is None:
        return '—'
    offset = local.strftime('%z')
    return f"{local:%d.%m.%Y %H:%M} (UTC{offset[:3]}:{offset[3:]})"


class ScheduleDateTimeWidget(forms.SplitDateTimeWidget):
    def __init__(self, zone):
        self.zone = zone
        # Native date/time controls avoid Django's Moscow-based 'Now' shortcut.
        super().__init__(date_attrs={'type': 'date'}, time_attrs={'type': 'time', 'step': '1'},
                         date_format='%Y-%m-%d', time_format='%H:%M:%S')

    def decompress(self, value):
        with timezone.override(self.zone):
            return super().decompress(value)


class ScheduleDateTimeField(forms.SplitDateTimeField):
    def __init__(self, zone, **kwargs):
        self.zone = zone
        super().__init__(widget=ScheduleDateTimeWidget(zone), **kwargs)

    def compress(self, data_list):
        with timezone.override(self.zone):
            return super().compress(data_list)

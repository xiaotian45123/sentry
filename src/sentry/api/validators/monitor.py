from __future__ import absolute_import

import six

from collections import OrderedDict
from croniter import croniter
from django.core.exceptions import ValidationError
from rest_framework import serializers

from sentry.models import MonitorStatus, MonitorType, ScheduleType
from sentry.api.serializers.rest_framework.project import ProjectField


SCHEDULE_TYPES = OrderedDict([
    ('crontab', ScheduleType.CRONTAB),
    ('interval', ScheduleType.INTERVAL),
])

MONITOR_TYPES = OrderedDict([
    ('cron_job', MonitorType.CRON_JOB),
])

MONITOR_STATUSES = OrderedDict([
    ('active', MonitorStatus.ACTIVE),
    ('disabled', MonitorStatus.DISABLED),
])

INTERVAL_NAMES = ('year', 'month', 'week', 'day', 'hour', 'minute')

# XXX(dcramer): @reboot is not supported (as it cannot be)
NONSTANDARD_CRONTAB_SCHEDULES = {
    '@yearly': '0 0 1 1 *',
    '@annually': '0 0 1 1 *',
    '@monthly': '0 0 1 * *',
    '@weekly': '0 0 * * 0',
    '@daily': '0 0 * * *',
    '@hourly': '0 * * * *',
}


class CronJobValidator(serializers.Field):
    def to_internal_value(self, data):
        result = {}
        schedule_type = None
        if 'schedule_type' in data:
            schedule_type = SCHEDULE_TYPES[data['schedule_type']]
        elif self.parent.instance:
            schedule_type = self.parent.instance['config']['schedule_type']
        result['schedule_type'] = schedule_type

        if 'checkin_margin' in data:
            try:
                result['checkin_margin'] = int(data['checkin_margin'])
            except ValueError:
                raise ValidationError('Invalid value for checkin_margin')
        else:
            result['checkin_margin'] = None
        if 'max_runtime' in data:
            try:
                result['max_runtime'] = int(data['max_runtime'])
            except ValueError:
                raise ValidationError('Invalid value for max_runtime')
        else:
            result['max_runtime'] = None

        value = data.get('schedule')
        if not value:
            return result

        if schedule_type == ScheduleType.INTERVAL:
            # type: [int count, str unit name]
            if not isinstance(value, list):
                raise ValidationError({'schedule': 'Invalid value for schedule_type'})
            if not isinstance(value[0], int):
                raise ValidationError(
                    {'schedule': 'Invalid value for schedule unit count (index 0)'})
            if value[1] not in INTERVAL_NAMES:
                raise ValidationError(
                    {'schedule': 'Invalid value for schedule unit name (index 1)'})
            result['schedule'] = value
        elif schedule_type == ScheduleType.CRONTAB:
            # type: str schedule
            if not isinstance(value, six.string_types):
                raise ValidationError({'schedule': 'Invalid value for schedule_type'})
            value = value.strip()
            if value.startswith('@'):
                try:
                    value = NONSTANDARD_CRONTAB_SCHEDULES[value]
                except KeyError:
                    raise ValidationError({'schedule': 'Schedule was not parseable'})
            if not croniter.is_valid(value):
                raise ValidationError({'schedule': 'Schedule was not parseable'})
            result['schedule'] = value
        return result


class MonitorValidator(serializers.Serializer):
    project = ProjectField()
    name = serializers.CharField()
    status = serializers.ChoiceField(
        choices=zip(MONITOR_STATUSES.keys(), MONITOR_STATUSES.keys()),
        default='active',
    )
    type = serializers.ChoiceField(
        choices=zip(MONITOR_TYPES.keys(), MONITOR_TYPES.keys())
    )

    def __init__(self, type=None, *args, **kwargs):
        super(MonitorValidator, self).__init__(*args, **kwargs)
        self.type = type

    def get_fields(self):
        fields = super(MonitorValidator, self).get_fields()
        type = self.type if self.type is not None else self.initial_data.get('type')
        if type in MONITOR_TYPES:
            type = MONITOR_TYPES[type]
        if type == MonitorType.CRON_JOB:
            fields['config'] = CronJobValidator()
        elif not type:
            return fields
        else:
            raise NotImplementedError
        return fields

    def validate_status(self, value):
        if value:
            value = MONITOR_STATUSES[value]
        return value

    def validate_type(self, value):
        if value:
            value = MONITOR_TYPES[value]
        return value

from __future__ import absolute_import

import sentry
import os

from django import template
from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.contrib.messages import get_messages
from django.db.models import F

from pkg_resources import parse_version

from sentry import features, options
from sentry.api.serializers.base import serialize
from sentry.api.serializers.models.user import DetailedUserSerializer
from sentry.auth.superuser import is_active_superuser
from sentry.cache import default_cache
from sentry.models import ProjectKey
from sentry.utils import auth, json
from sentry.utils.email import is_smtp_enabled
from sentry.utils.support import get_support_mail

register = template.Library()


def _get_version_info():
    current = sentry.VERSION

    latest = options.get('sentry:latest_version') or current
    upgrade_available = parse_version(latest) > parse_version(current)
    build = sentry.__build__ or current

    return {
        'current': current,
        'latest': latest,
        'build': build,
        'upgradeAvailable': upgrade_available,
    }


def _needs_upgrade():
    version_configured = options.get('sentry:version-configured')
    if not version_configured:
        # If we were never previously upgraded (being a new install)
        # we want to force an upgrade, even if the values are set.
        return True

    smtp_disabled = not is_smtp_enabled()

    # Check all required options to see if they've been set
    for key in options.filter(flag=options.FLAG_REQUIRED):
        # ignore required flags which can be empty
        if key.flags & options.FLAG_ALLOW_EMPTY:
            continue
        # Ignore mail.* keys if smtp is disabled
        if smtp_disabled and key.name[:5] == 'mail.':
            continue
        if not options.isset(key.name):
            return True

    if version_configured != sentry.get_version():
        # Everything looks good, but version changed, so let's bump it
        options.set('sentry:version-configured', sentry.get_version())

    return False


def _get_statuspage():
    id = settings.STATUS_PAGE_ID
    if id is None:
        return None
    return {'id': id, 'api_host': settings.STATUS_PAGE_API_HOST}


def _get_project_key(project_id):
    try:
        return ProjectKey.objects.filter(
            project=project_id,
            roles=F('roles').bitor(ProjectKey.roles.store),
        )[0]
    except IndexError:
        return None


def get_public_dsn():
    if settings.SENTRY_FRONTEND_DSN:
        return settings.SENTRY_FRONTEND_DSN

    project_id = settings.SENTRY_FRONTEND_PROJECT or settings.SENTRY_PROJECT
    cache_key = 'dsn:%s' % (project_id, )

    result = default_cache.get(cache_key)
    if result is None:
        key = _get_project_key(project_id)
        if key:
            result = key.dsn_public
        else:
            result = ''
        default_cache.set(cache_key, result, 60)
    return result


def get_user_context(request):
    user = getattr(request, 'user', None)
    result = {'ip_address': request.META['REMOTE_ADDR']}
    if user and user.is_authenticated():
        result.update({
            'email': user.email,
            'id': user.id,
        })
        if user.name:
            result['name'] = user.name
    return result


def get_build_context():
    build_identifier = os.environ.get("TRAVIS_BUILD_ID") or os.environ.get("SENTRY_BUILD_ID")
    if build_identifier:
        return {
            'id': build_identifier,
            'name': os.environ.get('TRAVIS_COMMIT_MESSAGE'),
            'commit': os.environ.get('TRAVIS_PULL_REQUEST_SHA') or os.environ.get('TRAVIS_COMMIT'),
        }
    return None


@register.simple_tag(takes_context=True)
def get_react_config(context):
    if 'request' in context:
        request = context['request']
        user = getattr(request, 'user', None) or AnonymousUser()
        messages = get_messages(request)
        session = getattr(request, 'session', None)
        is_superuser = is_active_superuser(request)
        user_context = get_user_context(request)
    else:
        user = None
        messages = []
        is_superuser = False
        user_context = {}

    enabled_features = []
    if features.has('organizations:create', actor=user):
        enabled_features.append('organizations:create')
    if auth.has_user_registration():
        enabled_features.append('auth:register')

    version_info = _get_version_info()

    needs_upgrade = False

    if is_superuser:
        needs_upgrade = _needs_upgrade()

    sentry_dsn = get_public_dsn()

    context = {
        'singleOrganization': settings.SENTRY_SINGLE_ORGANIZATION,
        'supportEmail': get_support_mail(),
        'urlPrefix': options.get('system.url-prefix'),
        'version': version_info,
        'features': enabled_features,
        'needsUpgrade': needs_upgrade,
        'dsn': sentry_dsn,
        'statuspage': _get_statuspage(),
        'messages': [{
            'message': msg.message,
            'level': msg.tags,
        } for msg in messages],
        'isOnPremise': settings.SENTRY_ONPREMISE,
        'invitesEnabled': settings.SENTRY_ENABLE_INVITES,
        'gravatarBaseUrl': settings.SENTRY_GRAVATAR_BASE_URL,
        'termsUrl': settings.TERMS_URL,
        'privacyUrl': settings.PRIVACY_URL,
        # Note `lastOrganization` should not be expected to update throughout frontend app lifecycle
        # It should only be used on a fresh browser nav to a path where an
        # organization is not in context
        'lastOrganization': session['activeorg'] if session and 'activeorg' in session else None,
        'csrfCookieName': settings.CSRF_COOKIE_NAME,
        'sentryConfig': {
            'dsn': sentry_dsn,
            'release': version_info['build'],
            'environment': settings.SENTRY_SDK_CONFIG['environment'],
            'whitelistUrls': list(settings.ALLOWED_HOSTS),
        },
        'buildContext': get_build_context(),
        'userContext': user_context,
    }
    if user and user.is_authenticated():
        context.update({
            'isAuthenticated': True,
            'user': serialize(user, user, DetailedUserSerializer()),
        })
        context['user']['isSuperuser'] = is_superuser
    else:
        context.update({
            'isAuthenticated': False,
            'user': None,
        })
    return json.dumps_htmlsafe(context)

from __future__ import absolute_import

import json
import six
from datetime import timedelta
from uuid import uuid4

from django.core.urlresolvers import reverse
from django.utils import timezone
from mock import patch, Mock

from sentry.models import (
    Activity, ApiToken, Event, EventMapping, ExternalIssue, Group, GroupAssignee,
    GroupBookmark, GroupHash, GroupLink, GroupSeen, GroupShare, GroupSnooze,
    GroupStatus, GroupResolution, GroupSubscription, GroupTombstone, Integration,
    OrganizationIntegration, UserOption, Release
)
from sentry.testutils import APITestCase, SnubaTestCase
from sentry.testutils.helpers import parse_link_header


class GroupListTest(APITestCase, SnubaTestCase):
    endpoint = 'sentry-api-0-organization-group-index'

    def setUp(self):
        super(GroupListTest, self).setUp()
        self.min_ago = timezone.now() - timedelta(minutes=1)

    def _parse_links(self, header):
        # links come in {url: {...attrs}}, but we need {rel: {...attrs}}
        links = {}
        for url, attrs in six.iteritems(parse_link_header(header)):
            links[attrs['rel']] = attrs
            attrs['href'] = url
        return links

    def get_response(self, *args, **kwargs):
        if not args:
            org = self.project.organization.slug
        else:
            org = args[0]
        return super(GroupListTest, self).get_response(org, **kwargs)

    def test_sort_by_date_with_tag(self):
        # XXX(dcramer): this tests a case where an ambiguous column name existed
        now = timezone.now()
        group1 = self.create_group(
            checksum='a' * 32,
            last_seen=now - timedelta(seconds=1),
        )
        self.create_event(
            group=group1,
            datetime=now - timedelta(seconds=1),
        )
        self.login_as(user=self.user)

        response = self.get_valid_response(sort_by='date', query='is:unresolved')
        assert len(response.data) == 1
        assert response.data[0]['id'] == six.text_type(group1.id)

    def test_feature_gate(self):
        # ensure there are two or more projects
        self.create_project(organization=self.project.organization)
        self.login_as(user=self.user)

        response = self.get_response()
        assert response.status_code == 400
        assert response.data['detail'] == 'You do not have the multi project stream feature enabled'

        with self.feature('organizations:global-views'):
            response = self.get_response()
            assert response.status_code == 200

    def test_boolean_search_feature_flag(self):
        self.login_as(user=self.user)
        response = self.get_response(sort_by='date', query='title:hello OR title:goodbye')
        assert response.status_code == 400
        assert response.data['detail'] == 'Your search query could not be parsed: Boolean statements containing "OR" or "AND" are not supported in this search'

        response = self.get_response(sort_by='date', query='title:hello AND title:goodbye')
        assert response.status_code == 400
        assert response.data['detail'] == 'Your search query could not be parsed: Boolean statements containing "OR" or "AND" are not supported in this search'

    def test_invalid_query(self):
        now = timezone.now()
        self.create_group(
            checksum='a' * 32,
            last_seen=now - timedelta(seconds=1),
        )
        self.login_as(user=self.user)

        response = self.get_response(sort_by='date', query='timesSeen:>1k')
        assert response.status_code == 400
        assert 'Invalid format for numeric search' in response.data['detail']

    def test_simple_pagination(self):
        now = timezone.now()
        group1 = self.create_group(
            project=self.project,
            last_seen=now - timedelta(seconds=2),
        )
        self.create_event(
            group=group1,
            datetime=now - timedelta(seconds=2),
        )
        group2 = self.create_group(
            project=self.project,
            last_seen=now - timedelta(seconds=1),
        )
        self.create_event(
            stacktrace=[['foo.py']],
            group=group2,
            datetime=now - timedelta(seconds=1),
        )
        self.login_as(user=self.user)
        response = self.get_valid_response(sort_by='date', limit=1)
        assert len(response.data) == 1
        assert response.data[0]['id'] == six.text_type(group2.id)

        links = self._parse_links(response['Link'])

        assert links['previous']['results'] == 'false'
        assert links['next']['results'] == 'true'

        response = self.client.get(links['next']['href'], format='json')
        assert response.status_code == 200
        assert len(response.data) == 1
        assert response.data[0]['id'] == six.text_type(group1.id)

        links = self._parse_links(response['Link'])

        assert links['previous']['results'] == 'true'
        assert links['next']['results'] == 'false'

    def test_stats_period(self):
        # TODO(dcramer): this test really only checks if validation happens
        # on groupStatsPeriod
        now = timezone.now()
        self.create_group(
            checksum='a' * 32,
            last_seen=now - timedelta(seconds=1),
        )
        self.create_group(
            checksum='b' * 32,
            last_seen=now,
        )

        self.login_as(user=self.user)

        self.get_valid_response(groupStatsPeriod='24h')
        self.get_valid_response(groupStatsPeriod='14d')
        self.get_valid_response(groupStatsPeriod='')
        response = self.get_response(groupStatsPeriod='48h')
        assert response.status_code == 400

    def test_environment(self):
        self.store_event(
            data={
                'fingerprint': ['put-me-in-group1'],
                'timestamp': self.min_ago.isoformat()[:19],
                'environment': 'production',
            },
            project_id=self.project.id
        )
        self.store_event(
            data={
                'fingerprint': ['put-me-in-group2'],
                'timestamp': self.min_ago.isoformat()[:19],
                'environment': 'staging',
            },
            project_id=self.project.id
        )

        self.login_as(user=self.user)

        response = self.get_valid_response(environment='production')
        assert len(response.data) == 1

        response = self.get_response(environment='garbage')
        assert response.status_code == 404

    def test_auto_resolved(self):
        project = self.project
        project.update_option('sentry:resolve_age', 1)
        now = timezone.now()
        group = self.create_group(
            checksum='a' * 32,
            last_seen=now - timedelta(days=1),
        )
        self.create_event(
            group=group,
            datetime=now - timedelta(days=1),
        )
        group2 = self.create_group(
            checksum='b' * 32,
            last_seen=now - timedelta(seconds=1),
        )
        self.create_event(
            group=group2,
            datetime=now - timedelta(seconds=1),
            stacktrace=[['foo.py']],
        )

        self.login_as(user=self.user)
        response = self.get_valid_response()
        assert len(response.data) == 1
        assert response.data[0]['id'] == six.text_type(group2.id)

    def test_lookup_by_event_id(self):
        project = self.project
        project.update_option('sentry:resolve_age', 1)
        group = self.create_group(checksum='a' * 32)
        self.create_group(checksum='b' * 32)
        event_id = 'c' * 32
        Event.objects.create(project_id=self.project.id, event_id=event_id)
        EventMapping.objects.create(
            event_id=event_id,
            project=group.project,
            group=group,
        )

        self.login_as(user=self.user)

        response = self.get_valid_response(query='c' * 32)
        assert response['X-Sentry-Direct-Hit'] == '1'
        assert len(response.data) == 1
        assert response.data[0]['id'] == six.text_type(group.id)
        assert response.data[0]['matchingEventId'] == event_id

    def test_lookup_by_event_id_incorrect_project_id(self):
        self.store_event(
            data={'event_id': 'a' * 32, 'timestamp': self.min_ago.isoformat()[:19]},
            project_id=self.project.id
        )
        event_id = 'b' * 32
        event = self.store_event(
            data={'event_id': event_id, 'timestamp': self.min_ago.isoformat()[:19]},
            project_id=self.project.id
        )

        other_project = self.create_project(teams=[self.team])
        user = self.create_user()
        self.create_member(
            organization=self.organization,
            teams=[self.team],
            user=user,
        )
        self.login_as(user=user)

        with self.feature('organizations:global-views'):
            response = self.get_valid_response(query=event_id, project=[other_project.id])
        assert response['X-Sentry-Direct-Hit'] == '1'
        assert len(response.data) == 1
        assert response.data[0]['id'] == six.text_type(event.group.id)
        assert response.data[0]['matchingEventId'] == event_id

    def test_lookup_by_event_id_with_whitespace(self):
        project = self.project
        project.update_option('sentry:resolve_age', 1)
        group = self.create_group(checksum='a' * 32)
        event_id = 'c' * 32
        self.create_group(checksum='b' * 32)
        EventMapping.objects.create(
            event_id=event_id,
            project=group.project,
            group=group,
        )

        self.login_as(user=self.user)
        response = self.get_valid_response(query='  {}  '.format('c' * 32))
        assert response['X-Sentry-Direct-Hit'] == '1'
        assert len(response.data) == 1
        assert response.data[0]['id'] == six.text_type(group.id)
        assert response.data[0]['matchingEventId'] == event_id

    def test_lookup_by_unknown_event_id(self):
        project = self.project
        project.update_option('sentry:resolve_age', 1)
        self.create_group(checksum='a' * 32)
        self.create_group(checksum='b' * 32)

        self.login_as(user=self.user)
        response = self.get_valid_response(query='c' * 32)
        assert len(response.data) == 0

    def test_lookup_by_short_id(self):
        group = self.group
        short_id = group.qualified_short_id

        self.login_as(user=self.user)
        response = self.get_valid_response(query=short_id, shortIdLookup=1)
        assert len(response.data) == 1

    def test_lookup_by_short_id_ignores_project_list(self):
        organization = self.create_organization()
        project = self.create_project(organization=organization)
        project2 = self.create_project(organization=organization)
        group = self.create_group(project=project2)
        user = self.create_user()
        self.create_member(organization=organization, user=user)

        short_id = group.qualified_short_id

        self.login_as(user=user)

        response = self.get_valid_response(
            organization.slug,
            project=project.id,
            query=short_id,
            shortIdLookup=1)
        assert len(response.data) == 1

    def test_lookup_by_short_id_no_perms(self):
        organization = self.create_organization()
        project = self.create_project(organization=organization)
        group = self.create_group(project=project)
        user = self.create_user()
        self.create_member(organization=organization, user=user, has_global_access=False)

        short_id = group.qualified_short_id

        self.login_as(user=user)

        response = self.get_valid_response(organization.slug, query=short_id, shortIdLookup=1)
        assert len(response.data) == 0

    def test_lookup_by_group_id(self):
        self.login_as(user=self.user)
        response = self.get_valid_response(group=self.group.id)
        assert len(response.data) == 1
        assert response.data[0]['id'] == six.text_type(self.group.id)
        group_2 = self.create_group()
        response = self.get_valid_response(group=[self.group.id, group_2.id])
        assert set([g['id'] for g in response.data]) == set([
            six.text_type(self.group.id),
            six.text_type(group_2.id),
        ])

    def test_lookup_by_group_id_no_perms(self):
        organization = self.create_organization()
        project = self.create_project(organization=organization)
        group = self.create_group(project=project)
        user = self.create_user()
        self.create_member(organization=organization, user=user, has_global_access=False)
        self.login_as(user=user)
        response = self.get_response(group=[group.id])
        assert response.status_code == 403

    def test_lookup_by_first_release(self):
        now = timezone.now()
        self.login_as(self.user)
        project = self.project
        project2 = self.create_project(name='baz', organization=project.organization)
        release = Release.objects.create(organization=project.organization, version='12345')
        release.add_project(project)
        release.add_project(project2)
        group = self.create_group(checksum='a' * 32, project=project, first_release=release)
        self.create_event(
            group=group,
            datetime=now - timedelta(seconds=1),
        )
        group2 = self.create_group(checksum='b' * 32, project=project2, first_release=release)
        self.create_event(
            group=group2,
            datetime=now - timedelta(seconds=1),
        )
        with self.feature('organizations:global-views'):
            response = self.get_valid_response(**{'first-release': '"%s"' % release.version})
        issues = json.loads(response.content)
        assert len(issues) == 2
        assert int(issues[0]['id']) == group2.id
        assert int(issues[1]['id']) == group.id

    def test_lookup_by_release(self):
        self.login_as(self.user)
        project = self.project
        release = Release.objects.create(organization=project.organization, version='12345')
        release.add_project(project)
        self.create_event(
            group=self.group,
            datetime=self.min_ago,
            tags={'sentry:release': release.version},
        )

        response = self.get_valid_response(release=release.version)
        issues = json.loads(response.content)
        assert len(issues) == 1
        assert int(issues[0]['id']) == self.group.id

    def test_pending_delete_pending_merge_excluded(self):
        group = self.create_group(
            checksum='a' * 32,
            status=GroupStatus.PENDING_DELETION,
        )
        self.create_event(
            group=group,
            datetime=self.min_ago,
            data={'checksum': 'a' * 32},
        )
        group2 = self.create_group(
            checksum='b' * 32,
        )
        self.create_event(
            group=group2,
            datetime=self.min_ago,
            data={'checksum': 'b' * 32},
        )
        group3 = self.create_group(
            checksum='c' * 32,
            status=GroupStatus.DELETION_IN_PROGRESS,
        )
        self.create_event(
            group=group3,
            datetime=self.min_ago,
            data={'checksum': 'c' * 32},
        )
        group4 = self.create_group(
            checksum='d' * 32,
            status=GroupStatus.PENDING_MERGE,
        )
        self.create_event(
            group=group4,
            datetime=self.min_ago,
            data={'checksum': 'd' * 32},
        )

        self.login_as(user=self.user)

        response = self.get_valid_response()
        assert len(response.data) == 1
        assert response.data[0]['id'] == six.text_type(group2.id)

    def test_filters_based_on_retention(self):
        self.login_as(user=self.user)

        self.create_group(last_seen=timezone.now() - timedelta(days=2))

        with self.options({'system.event-retention-days': 1}):
            response = self.get_valid_response()

        assert len(response.data) == 0

    def test_token_auth(self):
        token = ApiToken.objects.create(user=self.user, scope_list=['event:read'])
        response = self.client.get(
            reverse('sentry-api-0-organization-group-index', args=[self.project.organization.slug]),
            format='json',
            HTTP_AUTHORIZATION='Bearer %s' %
            token.token)
        assert response.status_code == 200, response.content

    def test_date_range(self):
        now = timezone.now()
        with self.options({'system.event-retention-days': 2}):
            group = self.create_group(
                last_seen=now - timedelta(hours=5),
                # first_seen needs to be accurate because of `shrink_time_window`
                first_seen=now - timedelta(hours=5),
                project=self.project,
            )

            self.create_event(
                group=group,
                datetime=now - timedelta(hours=5),
            )
            self.login_as(user=self.user)

            response = self.get_valid_response(statsPeriod='6h')
            assert len(response.data) == 1
            assert response.data[0]['id'] == six.text_type(group.id)

            response = self.get_valid_response(statsPeriod='1h')
            assert len(response.data) == 0

    @patch('sentry.analytics.record')
    def test_advanced_search_errors(self, mock_record):
        self.login_as(user=self.user)
        response = self.get_response(sort_by='date', query='!has:user')
        assert response.status_code == 200, response.data
        assert not any(
            c[0][0] == 'advanced_search.feature_gated' for c in mock_record.call_args_list)

        with self.feature({'organizations:advanced-search': False}):
            response = self.get_response(sort_by='date', query='!has:user')
            assert response.status_code == 400, response.data
            assert (
                'You need access to the advanced search feature to use negative '
                'search' == response.data['detail']
            )

            mock_record.assert_called_with(
                'advanced_search.feature_gated',
                user_id=self.user.id,
                default_user_id=self.user.id,
                organization_id=self.organization.id,
            )


class GroupUpdateTest(APITestCase, SnubaTestCase):
    endpoint = 'sentry-api-0-organization-group-index'
    method = 'put'

    def setUp(self):
        super(GroupUpdateTest, self).setUp()
        self.min_ago = timezone.now() - timedelta(minutes=1)

    def get_response(self, *args, **kwargs):
        if not args:
            org = self.project.organization.slug
        else:
            org = args[0]
        return super(GroupUpdateTest, self).get_response(org, **kwargs)

    def assertNoResolution(self, group):
        assert not GroupResolution.objects.filter(
            group=group,
        ).exists()

    def test_global_resolve(self):
        group1 = self.create_group(checksum='a' * 32, status=GroupStatus.RESOLVED)
        group2 = self.create_group(checksum='b' * 32, status=GroupStatus.UNRESOLVED)
        group3 = self.create_group(checksum='c' * 32, status=GroupStatus.IGNORED)
        group4 = self.create_group(
            project=self.create_project(slug='foo'),
            checksum='b' * 32,
            status=GroupStatus.UNRESOLVED
        )

        self.login_as(user=self.user)
        response = self.get_valid_response(
            qs_params={'status': 'unresolved', 'project': self.project.id},
            status='resolved',
        )
        assert response.data == {
            'status': 'resolved',
            'statusDetails': {},
        }

        # the previously resolved entry should not be included
        new_group1 = Group.objects.get(id=group1.id)
        assert new_group1.status == GroupStatus.RESOLVED
        assert new_group1.resolved_at is None

        # this wont exist because it wasn't affected
        assert not GroupSubscription.objects.filter(
            user=self.user,
            group=new_group1,
        ).exists()

        new_group2 = Group.objects.get(id=group2.id)
        assert new_group2.status == GroupStatus.RESOLVED
        assert new_group2.resolved_at is not None

        assert GroupSubscription.objects.filter(
            user=self.user,
            group=new_group2,
            is_active=True,
        ).exists()

        # the ignored entry should not be included
        new_group3 = Group.objects.get(id=group3.id)
        assert new_group3.status == GroupStatus.IGNORED
        assert new_group3.resolved_at is None

        assert not GroupSubscription.objects.filter(
            user=self.user,
            group=new_group3,
        )

        new_group4 = Group.objects.get(id=group4.id)
        assert new_group4.status == GroupStatus.UNRESOLVED
        assert new_group4.resolved_at is None

        assert not GroupSubscription.objects.filter(
            user=self.user,
            group=new_group4,
        )

    def test_resolve_member(self):
        group = self.create_group(checksum='a' * 32, status=GroupStatus.UNRESOLVED)
        member = self.create_user()
        self.create_member(
            organization=self.organization,
            teams=group.project.teams.all(),
            user=member,
        )

        self.login_as(user=member)
        response = self.get_valid_response(
            qs_params={'status': 'unresolved', 'project': self.project.id},
            status='resolved',
        )
        assert response.data == {
            'status': 'resolved',
            'statusDetails': {},
        }
        assert response.status_code == 200

    def test_bulk_resolve(self):
        self.login_as(user=self.user)

        for i in range(200):
            group = self.create_group(
                status=GroupStatus.UNRESOLVED,
                project=self.project,
                first_seen=self.min_ago - timedelta(seconds=i),
            )
            self.create_event(
                group=group,
                data={'checksum': six.binary_type(i)},
                datetime=self.min_ago - timedelta(seconds=i),
            )

        response = self.get_valid_response(
            query='is:unresolved',
            sort_by='date',
            method='get',
        )
        assert len(response.data) == 100

        response = self.get_valid_response(
            qs_params={'status': 'unresolved'},
            status='resolved',
        )
        assert response.data == {
            'status': 'resolved',
            'statusDetails': {},
        }

        response = self.get_valid_response(
            query='is:unresolved',
            sort_by='date',
            method='get',
        )
        assert len(response.data) == 0

    @patch('sentry.integrations.example.integration.ExampleIntegration.sync_status_outbound')
    def test_resolve_with_integration(self, mock_sync_status_outbound):
        self.login_as(user=self.user)

        org = self.organization

        integration = Integration.objects.create(
            provider='example',
            name='Example',
        )
        integration.add_organization(org, self.user)
        group = self.create_group(
            status=GroupStatus.UNRESOLVED,
            organization=org,
            first_seen=self.min_ago,
        )
        self.create_event(group=group, datetime=self.min_ago)

        OrganizationIntegration.objects.filter(
            integration_id=integration.id,
            organization_id=group.organization.id,
        ).update(
            config={
                'sync_comments': True,
                'sync_status_outbound': True,
                'sync_status_inbound': True,
                'sync_assignee_outbound': True,
                'sync_assignee_inbound': True,
            }
        )
        external_issue = ExternalIssue.objects.get_or_create(
            organization_id=org.id,
            integration_id=integration.id,
            key='APP-%s' % group.id,
        )[0]

        GroupLink.objects.get_or_create(
            group_id=group.id,
            project_id=group.project_id,
            linked_type=GroupLink.LinkedType.issue,
            linked_id=external_issue.id,
            relationship=GroupLink.Relationship.references,
        )[0]

        response = self.get_valid_response(sort_by='date', query='is:unresolved', method='get')
        assert len(response.data) == 1

        with self.tasks():
            with self.feature({
                'organizations:integrations-issue-sync': True,
            }):
                response = self.get_valid_response(
                    qs_params={'status': 'unresolved'},
                    status='resolved',
                )
                group = Group.objects.get(id=group.id)
                assert group.status == GroupStatus.RESOLVED

                assert response.data == {
                    'status': 'resolved',
                    'statusDetails': {},
                }
                mock_sync_status_outbound.assert_called_once_with(
                    external_issue, True, group.project_id
                )

        response = self.get_valid_response(sort_by='date', query='is:unresolved', method='get')
        assert len(response.data) == 0

    @patch('sentry.integrations.example.integration.ExampleIntegration.sync_status_outbound')
    def test_set_unresolved_with_integration(self, mock_sync_status_outbound):
        release = self.create_release(project=self.project, version='abc')
        group = self.create_group(checksum='a' * 32, status=GroupStatus.RESOLVED)
        org = self.organization
        integration = Integration.objects.create(
            provider='example',
            name='Example',
        )
        integration.add_organization(org, self.user)
        OrganizationIntegration.objects.filter(
            integration_id=integration.id,
            organization_id=group.organization.id,
        ).update(
            config={
                'sync_comments': True,
                'sync_status_outbound': True,
                'sync_status_inbound': True,
                'sync_assignee_outbound': True,
                'sync_assignee_inbound': True,
            }
        )
        GroupResolution.objects.create(
            group=group,
            release=release,
        )
        external_issue = ExternalIssue.objects.get_or_create(
            organization_id=org.id,
            integration_id=integration.id,
            key='APP-%s' % group.id,
        )[0]

        GroupLink.objects.get_or_create(
            group_id=group.id,
            project_id=group.project_id,
            linked_type=GroupLink.LinkedType.issue,
            linked_id=external_issue.id,
            relationship=GroupLink.Relationship.references,
        )[0]

        self.login_as(user=self.user)

        with self.tasks():
            with self.feature({
                'organizations:integrations-issue-sync': True,
            }):
                response = self.get_valid_response(
                    qs_params={'id': group.id},
                    status='unresolved',
                )
                assert response.status_code == 200
                assert response.data == {
                    'status': 'unresolved',
                    'statusDetails': {},
                }

                group = Group.objects.get(id=group.id)
                assert group.status == GroupStatus.UNRESOLVED

                self.assertNoResolution(group)

                assert GroupSubscription.objects.filter(
                    user=self.user,
                    group=group,
                    is_active=True,
                ).exists()
                mock_sync_status_outbound.assert_called_once_with(
                    external_issue, False, group.project_id
                )

    def test_self_assign_issue(self):
        group = self.create_group(checksum='b' * 32, status=GroupStatus.UNRESOLVED)
        user = self.user

        uo1 = UserOption.objects.create(key='self_assign_issue', value='1', project=None, user=user)

        self.login_as(user=user)
        response = self.get_valid_response(
            qs_params={'id': group.id},
            status='resolved',
        )
        assert response.data['assignedTo']['id'] == six.text_type(user.id)
        assert response.data['assignedTo']['type'] == 'user'
        assert response.data['status'] == 'resolved'

        assert GroupAssignee.objects.filter(group=group, user=user).exists()

        assert GroupSubscription.objects.filter(
            user=user,
            group=group,
            is_active=True,
        ).exists()

        uo1.delete()

    def test_self_assign_issue_next_release(self):
        release = Release.objects.create(organization_id=self.project.organization_id, version='a')
        release.add_project(self.project)

        group = self.create_group(
            checksum='a' * 32,
            status=GroupStatus.UNRESOLVED,
        )

        uo1 = UserOption.objects.create(
            key='self_assign_issue', value='1', project=None, user=self.user
        )

        self.login_as(user=self.user)

        response = self.get_valid_response(
            qs_params={'id': group.id},
            status='resolvedInNextRelease',
        )
        assert response.data['status'] == 'resolved'
        assert response.data['statusDetails']['inNextRelease']
        assert response.data['assignedTo']['id'] == six.text_type(self.user.id)
        assert response.data['assignedTo']['type'] == 'user'

        group = Group.objects.get(id=group.id)
        assert group.status == GroupStatus.RESOLVED

        assert GroupResolution.objects.filter(
            group=group,
            release=release,
        ).exists()

        assert GroupSubscription.objects.filter(
            user=self.user,
            group=group,
            is_active=True,
        ).exists()

        activity = Activity.objects.get(
            group=group,
            type=Activity.SET_RESOLVED_IN_RELEASE,
        )
        assert activity.data['version'] == ''
        uo1.delete()

    def test_selective_status_update(self):
        group1 = self.create_group(checksum='a' * 32, status=GroupStatus.RESOLVED)
        group2 = self.create_group(checksum='b' * 32, status=GroupStatus.UNRESOLVED)
        group3 = self.create_group(checksum='c' * 32, status=GroupStatus.IGNORED)
        group4 = self.create_group(
            project=self.create_project(slug='foo'),
            checksum='b' * 32,
            status=GroupStatus.UNRESOLVED
        )

        self.login_as(user=self.user)
        with self.feature('organizations:global-views'):
            response = self.get_valid_response(
                qs_params={'id': [group1.id, group2.id], 'group4': group4.id},
                status='resolved',
            )
        assert response.data == {
            'status': 'resolved',
            'statusDetails': {},
        }

        new_group1 = Group.objects.get(id=group1.id)
        assert new_group1.resolved_at is not None
        assert new_group1.status == GroupStatus.RESOLVED

        new_group2 = Group.objects.get(id=group2.id)
        assert new_group2.resolved_at is not None
        assert new_group2.status == GroupStatus.RESOLVED

        assert GroupSubscription.objects.filter(
            user=self.user,
            group=new_group2,
            is_active=True,
        ).exists()

        new_group3 = Group.objects.get(id=group3.id)
        assert new_group3.resolved_at is None
        assert new_group3.status == GroupStatus.IGNORED

        new_group4 = Group.objects.get(id=group4.id)
        assert new_group4.resolved_at is None
        assert new_group4.status == GroupStatus.UNRESOLVED

    def test_set_resolved_in_current_release(self):
        release = Release.objects.create(organization_id=self.project.organization_id, version='a')
        release.add_project(self.project)

        group = self.create_group(
            checksum='a' * 32,
            status=GroupStatus.UNRESOLVED,
        )

        self.login_as(user=self.user)

        response = self.get_valid_response(
            qs_params={'id': group.id},
            status='resolved',
            statusDetails={'inRelease': 'latest'},
        )
        assert response.data['status'] == 'resolved'
        assert response.data['statusDetails']['inRelease'] == release.version
        assert response.data['statusDetails']['actor']['id'] == six.text_type(self.user.id)

        group = Group.objects.get(id=group.id)
        assert group.status == GroupStatus.RESOLVED

        resolution = GroupResolution.objects.get(
            group=group,
        )
        assert resolution.release == release
        assert resolution.type == GroupResolution.Type.in_release
        assert resolution.status == GroupResolution.Status.resolved
        assert resolution.actor_id == self.user.id

        assert GroupSubscription.objects.filter(
            user=self.user,
            group=group,
            is_active=True,
        ).exists()

        activity = Activity.objects.get(
            group=group,
            type=Activity.SET_RESOLVED_IN_RELEASE,
        )
        assert activity.data['version'] == release.version

    def test_set_resolved_in_explicit_release(self):
        release = Release.objects.create(organization_id=self.project.organization_id, version='a')
        release.add_project(self.project)
        release2 = Release.objects.create(organization_id=self.project.organization_id, version='b')
        release2.add_project(self.project)

        group = self.create_group(
            checksum='a' * 32,
            status=GroupStatus.UNRESOLVED,
        )

        self.login_as(user=self.user)

        response = self.get_valid_response(
            qs_params={'id': group.id},
            status='resolved',
            statusDetails={'inRelease': release.version},
        )
        assert response.data['status'] == 'resolved'
        assert response.data['statusDetails']['inRelease'] == release.version
        assert response.data['statusDetails']['actor']['id'] == six.text_type(self.user.id)

        group = Group.objects.get(id=group.id)
        assert group.status == GroupStatus.RESOLVED

        resolution = GroupResolution.objects.get(
            group=group,
        )
        assert resolution.release == release
        assert resolution.type == GroupResolution.Type.in_release
        assert resolution.status == GroupResolution.Status.resolved
        assert resolution.actor_id == self.user.id

        assert GroupSubscription.objects.filter(
            user=self.user,
            group=group,
            is_active=True,
        ).exists()

        activity = Activity.objects.get(
            group=group,
            type=Activity.SET_RESOLVED_IN_RELEASE,
        )
        assert activity.data['version'] == release.version

    def test_set_resolved_in_next_release(self):
        release = Release.objects.create(organization_id=self.project.organization_id, version='a')
        release.add_project(self.project)

        group = self.create_group(
            checksum='a' * 32,
            status=GroupStatus.UNRESOLVED,
        )

        self.login_as(user=self.user)

        response = self.get_valid_response(
            qs_params={'id': group.id},
            status='resolved',
            statusDetails={'inNextRelease': True},
        )
        assert response.data['status'] == 'resolved'
        assert response.data['statusDetails']['inNextRelease']
        assert response.data['statusDetails']['actor']['id'] == six.text_type(self.user.id)

        group = Group.objects.get(id=group.id)
        assert group.status == GroupStatus.RESOLVED

        resolution = GroupResolution.objects.get(
            group=group,
        )
        assert resolution.release == release
        assert resolution.type == GroupResolution.Type.in_next_release
        assert resolution.status == GroupResolution.Status.pending
        assert resolution.actor_id == self.user.id

        assert GroupSubscription.objects.filter(
            user=self.user,
            group=group,
            is_active=True,
        ).exists()

        activity = Activity.objects.get(
            group=group,
            type=Activity.SET_RESOLVED_IN_RELEASE,
        )
        assert activity.data['version'] == ''

    def test_set_resolved_in_next_release_legacy(self):
        release = Release.objects.create(organization_id=self.project.organization_id, version='a')
        release.add_project(self.project)

        group = self.create_group(
            checksum='a' * 32,
            status=GroupStatus.UNRESOLVED,
        )

        self.login_as(user=self.user)

        response = self.get_valid_response(
            qs_params={'id': group.id},
            status='resolvedInNextRelease',
        )
        assert response.data['status'] == 'resolved'
        assert response.data['statusDetails']['inNextRelease']
        assert response.data['statusDetails']['actor']['id'] == six.text_type(self.user.id)

        group = Group.objects.get(id=group.id)
        assert group.status == GroupStatus.RESOLVED

        resolution = GroupResolution.objects.get(
            group=group,
        )
        assert resolution.release == release
        assert resolution.type == GroupResolution.Type.in_next_release
        assert resolution.status == GroupResolution.Status.pending
        assert resolution.actor_id == self.user.id

        assert GroupSubscription.objects.filter(
            user=self.user,
            group=group,
            is_active=True,
        ).exists()

        activity = Activity.objects.get(
            group=group,
            type=Activity.SET_RESOLVED_IN_RELEASE,
        )
        assert activity.data['version'] == ''

    def test_set_resolved_in_explicit_commit_unreleased(self):
        repo = self.create_repo(
            project=self.project,
            name=self.project.name,
        )
        commit = self.create_commit(
            project=self.project,
            repo=repo,
        )
        group = self.create_group(
            checksum='a' * 32,
            status=GroupStatus.UNRESOLVED,
        )

        self.login_as(user=self.user)

        response = self.get_valid_response(
            qs_params={'id': group.id},
            status='resolved',
            statusDetails={'inCommit': {'commit': commit.key, 'repository': repo.name}},
        )
        assert response.data['status'] == 'resolved'
        assert response.data['statusDetails']['inCommit']['id'] == commit.key
        assert response.data['statusDetails']['actor']['id'] == six.text_type(self.user.id)

        group = Group.objects.get(id=group.id)
        assert group.status == GroupStatus.RESOLVED

        link = GroupLink.objects.get(group_id=group.id)
        assert link.linked_type == GroupLink.LinkedType.commit
        assert link.relationship == GroupLink.Relationship.resolves
        assert link.linked_id == commit.id

        assert GroupSubscription.objects.filter(
            user=self.user,
            group=group,
            is_active=True,
        ).exists()

        activity = Activity.objects.get(
            group=group,
            type=Activity.SET_RESOLVED_IN_COMMIT,
        )
        assert activity.data['commit'] == commit.id

    def test_set_resolved_in_explicit_commit_released(self):
        release = self.create_release(
            project=self.project,
        )
        repo = self.create_repo(
            project=self.project,
            name=self.project.name,
        )
        commit = self.create_commit(
            project=self.project,
            repo=repo,
            release=release,
        )

        group = self.create_group(
            checksum='a' * 32,
            status=GroupStatus.UNRESOLVED,
        )

        self.login_as(user=self.user)

        response = self.get_valid_response(
            qs_params={'id': group.id},
            status='resolved',
            statusDetails={'inCommit': {'commit': commit.key, 'repository': repo.name}},
        )
        assert response.data['status'] == 'resolved'
        assert response.data['statusDetails']['inCommit']['id'] == commit.key
        assert response.data['statusDetails']['actor']['id'] == six.text_type(self.user.id)

        group = Group.objects.get(id=group.id)
        assert group.status == GroupStatus.RESOLVED

        link = GroupLink.objects.get(group_id=group.id)
        assert link.project_id == self.project.id
        assert link.linked_type == GroupLink.LinkedType.commit
        assert link.relationship == GroupLink.Relationship.resolves
        assert link.linked_id == commit.id

        assert GroupSubscription.objects.filter(
            user=self.user,
            group=group,
            is_active=True,
        ).exists()

        activity = Activity.objects.get(
            group=group,
            type=Activity.SET_RESOLVED_IN_COMMIT,
        )
        assert activity.data['commit'] == commit.id

        resolution = GroupResolution.objects.get(
            group=group,
        )
        assert resolution.type == GroupResolution.Type.in_release
        assert resolution.status == GroupResolution.Status.resolved

    def test_set_resolved_in_explicit_commit_missing(self):
        repo = self.create_repo(
            project=self.project,
            name=self.project.name,
        )
        group = self.create_group(
            checksum='a' * 32,
            status=GroupStatus.UNRESOLVED,
        )

        self.login_as(user=self.user)

        response = self.get_response(
            qs_params={'id': group.id},
            status='resolved',
            statusDetails={'inCommit': {'commit': 'a' * 40, 'repository': repo.name}},
        )
        assert response.status_code == 400
        assert response.data['statusDetails'][0]['inCommit'][0]['commit']

    def test_set_unresolved(self):
        release = self.create_release(project=self.project, version='abc')
        group = self.create_group(checksum='a' * 32, status=GroupStatus.RESOLVED)
        GroupResolution.objects.create(
            group=group,
            release=release,
        )

        self.login_as(user=self.user)

        response = self.get_valid_response(qs_params={'id': group.id}, status='unresolved')
        assert response.data == {
            'status': 'unresolved',
            'statusDetails': {},
        }

        group = Group.objects.get(id=group.id)
        assert group.status == GroupStatus.UNRESOLVED

        self.assertNoResolution(group)

        assert GroupSubscription.objects.filter(
            user=self.user,
            group=group,
            is_active=True,
        ).exists()

    def test_set_unresolved_on_snooze(self):
        group = self.create_group(checksum='a' * 32, status=GroupStatus.IGNORED)

        GroupSnooze.objects.create(
            group=group,
            until=timezone.now() - timedelta(days=1),
        )

        self.login_as(user=self.user)

        response = self.get_valid_response(qs_params={'id': group.id}, status='unresolved')
        assert response.data == {
            'status': 'unresolved',
            'statusDetails': {},
        }

        group = Group.objects.get(id=group.id)
        assert group.status == GroupStatus.UNRESOLVED

    def test_basic_ignore(self):
        group = self.create_group(checksum='a' * 32, status=GroupStatus.RESOLVED)

        snooze = GroupSnooze.objects.create(
            group=group,
            until=timezone.now(),
        )

        self.login_as(user=self.user)

        response = self.get_valid_response(qs_params={'id': group.id}, status='ignored')
        # existing snooze objects should be cleaned up
        assert not GroupSnooze.objects.filter(id=snooze.id).exists()

        group = Group.objects.get(id=group.id)
        assert group.status == GroupStatus.IGNORED

        assert response.data == {
            'status': 'ignored',
            'statusDetails': {},
        }

    def test_snooze_duration(self):
        group = self.create_group(checksum='a' * 32, status=GroupStatus.RESOLVED)

        self.login_as(user=self.user)

        response = self.get_valid_response(
            qs_params={'id': group.id},
            status='ignored',
            ignoreDuration=30,
        )
        snooze = GroupSnooze.objects.get(group=group)
        snooze.until = snooze.until

        now = timezone.now()

        assert snooze.count is None
        assert snooze.until > now + timedelta(minutes=29)
        assert snooze.until < now + timedelta(minutes=31)
        assert snooze.user_count is None
        assert snooze.user_window is None
        assert snooze.window is None

        response.data['statusDetails']['ignoreUntil'] = response.data['statusDetails']['ignoreUntil']

        assert response.data['status'] == 'ignored'
        assert response.data['statusDetails']['ignoreCount'] == snooze.count
        assert response.data['statusDetails']['ignoreWindow'] == snooze.window
        assert response.data['statusDetails']['ignoreUserCount'] == snooze.user_count
        assert response.data['statusDetails']['ignoreUserWindow'] == snooze.user_window
        assert response.data['statusDetails']['ignoreUntil'] == snooze.until
        assert response.data['statusDetails']['actor']['id'] == six.text_type(self.user.id)

    def test_snooze_count(self):
        group = self.create_group(
            checksum='a' * 32,
            status=GroupStatus.RESOLVED,
            times_seen=1,
        )

        self.login_as(user=self.user)

        response = self.get_valid_response(
            qs_params={'id': group.id},
            status='ignored',
            ignoreCount=100,
        )
        snooze = GroupSnooze.objects.get(group=group)
        assert snooze.count == 100
        assert snooze.until is None
        assert snooze.user_count is None
        assert snooze.user_window is None
        assert snooze.window is None
        assert snooze.state['times_seen'] == 1

        assert response.data['status'] == 'ignored'
        assert response.data['statusDetails']['ignoreCount'] == snooze.count
        assert response.data['statusDetails']['ignoreWindow'] == snooze.window
        assert response.data['statusDetails']['ignoreUserCount'] == snooze.user_count
        assert response.data['statusDetails']['ignoreUserWindow'] == snooze.user_window
        assert response.data['statusDetails']['ignoreUntil'] == snooze.until
        assert response.data['statusDetails']['actor']['id'] == six.text_type(self.user.id)

    def test_snooze_user_count(self):
        for i in range(10):
            event = self.store_event(
                data={
                    'fingerprint': ['put-me-in-group-1'],
                    'user': {'id': six.binary_type(i)},
                    'timestamp': (self.min_ago - timedelta(seconds=i)).isoformat()[:19]
                },
                project_id=self.project.id
            )

        group = Group.objects.get(id=event.group.id)
        group.status = GroupStatus.RESOLVED
        group.save()

        self.login_as(user=self.user)

        response = self.get_valid_response(
            qs_params={'id': group.id},
            status='ignored',
            ignoreUserCount=10,
        )
        snooze = GroupSnooze.objects.get(group=group)
        assert snooze.count is None
        assert snooze.until is None
        assert snooze.user_count == 10
        assert snooze.user_window is None
        assert snooze.window is None
        assert snooze.state['users_seen'] == 10

        assert response.data['status'] == 'ignored'
        assert response.data['statusDetails']['ignoreCount'] == snooze.count
        assert response.data['statusDetails']['ignoreWindow'] == snooze.window
        assert response.data['statusDetails']['ignoreUserCount'] == snooze.user_count
        assert response.data['statusDetails']['ignoreUserWindow'] == snooze.user_window
        assert response.data['statusDetails']['ignoreUntil'] == snooze.until
        assert response.data['statusDetails']['actor']['id'] == six.text_type(self.user.id)

    def test_set_bookmarked(self):
        group1 = self.create_group(checksum='a' * 32, status=GroupStatus.RESOLVED)
        group2 = self.create_group(checksum='b' * 32, status=GroupStatus.UNRESOLVED)
        group3 = self.create_group(checksum='c' * 32, status=GroupStatus.IGNORED)
        group4 = self.create_group(
            project=self.create_project(slug='foo'),
            checksum='b' * 32,
            status=GroupStatus.UNRESOLVED
        )

        self.login_as(user=self.user)
        with self.feature('organizations:global-views'):
            response = self.get_valid_response(
                qs_params={'id': [group1.id, group2.id], 'group4': group4.id},
                isBookmarked='true',
            )
        assert response.data == {
            'isBookmarked': True,
        }

        bookmark1 = GroupBookmark.objects.filter(group=group1, user=self.user)
        assert bookmark1.exists()

        assert GroupSubscription.objects.filter(
            user=self.user,
            group=group1,
            is_active=True,
        ).exists()

        bookmark2 = GroupBookmark.objects.filter(group=group2, user=self.user)
        assert bookmark2.exists()

        assert GroupSubscription.objects.filter(
            user=self.user,
            group=group2,
            is_active=True,
        ).exists()

        bookmark3 = GroupBookmark.objects.filter(group=group3, user=self.user)
        assert not bookmark3.exists()

        bookmark4 = GroupBookmark.objects.filter(group=group4, user=self.user)
        assert not bookmark4.exists()

    def test_subscription(self):
        group1 = self.create_group(checksum='a' * 32)
        group2 = self.create_group(checksum='b' * 32)
        group3 = self.create_group(checksum='c' * 32)
        group4 = self.create_group(project=self.create_project(slug='foo'), checksum='b' * 32)

        self.login_as(user=self.user)
        with self.feature('organizations:global-views'):
            response = self.get_valid_response(
                qs_params={'id': [group1.id, group2.id], 'group4': group4.id},
                isSubscribed='true',
            )
        assert response.data == {
            'isSubscribed': True,
            'subscriptionDetails': {
                'reason': 'unknown',
            },
        }

        assert GroupSubscription.objects.filter(
            group=group1,
            user=self.user,
            is_active=True,
        ).exists()

        assert GroupSubscription.objects.filter(
            group=group2,
            user=self.user,
            is_active=True,
        ).exists()

        assert not GroupSubscription.objects.filter(
            group=group3,
            user=self.user,
        ).exists()

        assert not GroupSubscription.objects.filter(
            group=group4,
            user=self.user,
        ).exists()

    def test_set_public(self):
        group1 = self.create_group(checksum='a' * 32)
        group2 = self.create_group(checksum='b' * 32)

        self.login_as(user=self.user)
        response = self.get_valid_response(
            qs_params={'id': [group1.id, group2.id]},
            isPublic='true',
        )
        assert response.data['isPublic'] is True
        assert 'shareId' in response.data

        new_group1 = Group.objects.get(id=group1.id)
        assert bool(new_group1.get_share_id())

        new_group2 = Group.objects.get(id=group2.id)
        assert bool(new_group2.get_share_id())

    def test_set_private(self):
        group1 = self.create_group(checksum='a' * 32)
        group2 = self.create_group(checksum='b' * 32)

        # Manually mark them as shared
        for g in group1, group2:
            GroupShare.objects.create(
                project_id=g.project_id,
                group=g,
            )
            assert bool(g.get_share_id())

        self.login_as(user=self.user)
        response = self.get_valid_response(
            qs_params={'id': [group1.id, group2.id]},
            isPublic='false',
        )
        assert response.data == {
            'isPublic': False,
        }

        new_group1 = Group.objects.get(id=group1.id)
        assert not bool(new_group1.get_share_id())

        new_group2 = Group.objects.get(id=group2.id)
        assert not bool(new_group2.get_share_id())

    def test_set_has_seen(self):
        group1 = self.create_group(checksum='a' * 32, status=GroupStatus.RESOLVED)
        group2 = self.create_group(checksum='b' * 32, status=GroupStatus.UNRESOLVED)
        group3 = self.create_group(checksum='c' * 32, status=GroupStatus.IGNORED)
        group4 = self.create_group(
            project=self.create_project(slug='foo'),
            checksum='b' * 32,
            status=GroupStatus.UNRESOLVED
        )

        self.login_as(user=self.user)
        with self.feature('organizations:global-views'):
            response = self.get_valid_response(
                qs_params={'id': [group1.id, group2.id], 'group4': group4.id},
                hasSeen='true',
            )
        assert response.data == {
            'hasSeen': True,
        }

        r1 = GroupSeen.objects.filter(group=group1, user=self.user)
        assert r1.exists()

        r2 = GroupSeen.objects.filter(group=group2, user=self.user)
        assert r2.exists()

        r3 = GroupSeen.objects.filter(group=group3, user=self.user)
        assert not r3.exists()

        r4 = GroupSeen.objects.filter(group=group4, user=self.user)
        assert not r4.exists()

    @patch('sentry.api.helpers.group_index.uuid4')
    @patch('sentry.api.helpers.group_index.merge_groups')
    @patch('sentry.api.helpers.group_index.eventstream')
    def test_merge(self, mock_eventstream, merge_groups, mock_uuid4):
        eventstream_state = object()
        mock_eventstream.start_merge = Mock(return_value=eventstream_state)

        class uuid(object):
            hex = 'abc123'

        mock_uuid4.return_value = uuid
        group1 = self.create_group(checksum='a' * 32, times_seen=1)
        group2 = self.create_group(checksum='b' * 32, times_seen=50)
        group3 = self.create_group(checksum='c' * 32, times_seen=2)
        self.create_group(checksum='d' * 32)

        self.login_as(user=self.user)
        response = self.get_valid_response(
            qs_params={'id': [group1.id, group2.id, group3.id]},
            merge='1',
        )
        assert response.data['merge']['parent'] == six.text_type(group2.id)
        assert sorted(response.data['merge']['children']) == sorted(
            [
                six.text_type(group1.id),
                six.text_type(group3.id),
            ]
        )

        mock_eventstream.start_merge.assert_called_once_with(
            group1.project_id, [group3.id, group1.id], group2.id)

        assert len(merge_groups.mock_calls) == 1
        merge_groups.delay.assert_any_call(
            from_object_ids=[group3.id, group1.id],
            to_object_id=group2.id,
            transaction_id='abc123',
            eventstream_state=eventstream_state,
        )

    def test_assign(self):
        group1 = self.create_group(checksum='a' * 32, is_public=True)
        group2 = self.create_group(checksum='b' * 32, is_public=True)
        user = self.user

        self.login_as(user=user)
        response = self.get_valid_response(
            qs_params={'id': group1.id},
            assignedTo=user.username,
        )
        assert response.data['assignedTo']['id'] == six.text_type(user.id)
        assert response.data['assignedTo']['type'] == 'user'
        assert GroupAssignee.objects.filter(group=group1, user=user).exists()

        assert not GroupAssignee.objects.filter(group=group2, user=user).exists()

        assert Activity.objects.filter(
            group=group1,
            user=user,
            type=Activity.ASSIGNED,
        ).count() == 1

        assert GroupSubscription.objects.filter(
            user=user,
            group=group1,
            is_active=True,
        ).exists()

        response = self.get_valid_response(
            qs_params={'id': group1.id},
            assignedTo='',
        )
        assert response.data['assignedTo'] is None

        assert not GroupAssignee.objects.filter(group=group1, user=user).exists()

    def test_assign_non_member(self):
        group = self.create_group(checksum='a' * 32, is_public=True)
        member = self.user
        non_member = self.create_user('bar@example.com')

        self.login_as(user=member)

        response = self.get_response(
            qs_params={'id': group.id},
            assignedTo=non_member.username,
        )
        assert response.status_code == 400, response.content

    def test_assign_team(self):
        self.login_as(user=self.user)

        group = self.create_group()
        other_member = self.create_user('bar@example.com')
        team = self.create_team(
            organization=group.project.organization, members=[
                self.user, other_member])

        group.project.add_team(team)

        response = self.get_valid_response(
            qs_params={'id': group.id},
            assignedTo=u'team:{}'.format(team.id),
        )
        assert response.data['assignedTo']['id'] == six.text_type(team.id)
        assert response.data['assignedTo']['type'] == 'team'
        assert GroupAssignee.objects.filter(group=group, team=team).exists()

        assert Activity.objects.filter(
            group=group,
            type=Activity.ASSIGNED,
        ).count() == 1

        assert GroupSubscription.objects.filter(
            group=group,
            is_active=True,
        ).count() == 2

        response = self.get_valid_response(
            qs_params={'id': group.id},
            assignedTo='',
        )
        assert response.data['assignedTo'] is None

    def test_discard(self):
        group1 = self.create_group(checksum='a' * 32, is_public=True)
        group2 = self.create_group(checksum='b' * 32, is_public=True)
        group_hash = GroupHash.objects.create(
            hash='x' * 32,
            project=group1.project,
            group=group1,
        )
        user = self.user

        self.login_as(user=user)
        with self.tasks():
            with self.feature('projects:discard-groups'):
                response = self.get_response(
                    qs_params={'id': group1.id},
                    discard=True,
                )

        assert response.status_code == 204
        assert not Group.objects.filter(
            id=group1.id,
        ).exists()
        assert Group.objects.filter(
            id=group2.id,
        ).exists()
        assert GroupHash.objects.filter(
            id=group_hash.id,
        ).exists()
        tombstone = GroupTombstone.objects.get(
            id=GroupHash.objects.get(id=group_hash.id).group_tombstone_id,
        )
        assert tombstone.message == group1.message
        assert tombstone.culprit == group1.culprit
        assert tombstone.project == group1.project
        assert tombstone.data == group1.data


class GroupDeleteTest(APITestCase, SnubaTestCase):
    endpoint = 'sentry-api-0-organization-group-index'
    method = 'delete'

    def get_response(self, *args, **kwargs):
        if not args:
            org = self.project.organization.slug
        else:
            org = args[0]
        return super(GroupDeleteTest, self).get_response(org, **kwargs)

    @patch('sentry.api.helpers.group_index.eventstream')
    @patch('sentry.eventstream')
    def test_delete_by_id(self, mock_eventstream_task, mock_eventstream_api):
        eventstream_state = object()
        mock_eventstream_api.start_delete_groups = Mock(return_value=eventstream_state)

        group1 = self.create_group(checksum='a' * 32, status=GroupStatus.RESOLVED)
        group2 = self.create_group(checksum='b' * 32, status=GroupStatus.UNRESOLVED)
        group3 = self.create_group(checksum='c' * 32, status=GroupStatus.IGNORED)
        group4 = self.create_group(
            project=self.create_project(slug='foo'),
            checksum='b' * 32,
            status=GroupStatus.UNRESOLVED
        )

        hashes = []
        for g in group1, group2, group3, group4:
            hash = uuid4().hex
            hashes.append(hash)
            GroupHash.objects.create(
                project=g.project,
                hash=hash,
                group=g,
            )

        self.login_as(user=self.user)
        with self.feature('organizations:global-views'):
            response = self.get_response(
                qs_params={'id': [group1.id, group2.id], 'group4': group4.id},
            )

        mock_eventstream_api.start_delete_groups.assert_called_once_with(
            group1.project_id, [group1.id, group2.id])

        assert response.status_code == 204

        assert Group.objects.get(id=group1.id).status == GroupStatus.PENDING_DELETION
        assert not GroupHash.objects.filter(group_id=group1.id).exists()

        assert Group.objects.get(id=group2.id).status == GroupStatus.PENDING_DELETION
        assert not GroupHash.objects.filter(group_id=group2.id).exists()

        assert Group.objects.get(id=group3.id).status != GroupStatus.PENDING_DELETION
        assert GroupHash.objects.filter(group_id=group3.id).exists()

        assert Group.objects.get(id=group4.id).status != GroupStatus.PENDING_DELETION
        assert GroupHash.objects.filter(group_id=group4.id).exists()

        Group.objects.filter(id__in=(group1.id, group2.id)).update(status=GroupStatus.UNRESOLVED)

        with self.tasks():
            with self.feature('organizations:global-views'):
                response = self.get_response(
                    qs_params={'id': [group1.id, group2.id], 'group4': group4.id},
                )

        mock_eventstream_task.end_delete_groups.assert_called_once_with(eventstream_state)

        assert response.status_code == 204

        assert not Group.objects.filter(id=group1.id).exists()
        assert not GroupHash.objects.filter(group_id=group1.id).exists()

        assert not Group.objects.filter(id=group2.id).exists()
        assert not GroupHash.objects.filter(group_id=group2.id).exists()

        assert Group.objects.filter(id=group3.id).exists()
        assert GroupHash.objects.filter(group_id=group3.id).exists()

        assert Group.objects.filter(id=group4.id).exists()
        assert GroupHash.objects.filter(group_id=group4.id).exists()

    def test_bulk_delete(self):
        groups = []
        for i in range(10, 41):
            groups.append(
                self.create_group(
                    project=self.project,
                    checksum=six.binary_type(i) * 16,
                    status=GroupStatus.RESOLVED))

        hashes = []
        for group in groups:
            hash = uuid4().hex
            hashes.append(hash)
            GroupHash.objects.create(
                project=group.project,
                hash=hash,
                group=group,
            )

        self.login_as(user=self.user)

        # if query is '' it defaults to is:unresolved
        response = self.get_response(qs_params={'query': ''})
        assert response.status_code == 204

        for group in groups:
            assert Group.objects.get(id=group.id).status == GroupStatus.PENDING_DELETION
            assert not GroupHash.objects.filter(group_id=group.id).exists()

        Group.objects.filter(
            id__in=[
                group.id for group in groups]).update(
            status=GroupStatus.UNRESOLVED)

        with self.tasks():
            response = self.get_response(qs_params={'query': ''})

        assert response.status_code == 204

        for group in groups:
            assert not Group.objects.filter(id=group.id).exists()
            assert not GroupHash.objects.filter(group_id=group.id).exists()

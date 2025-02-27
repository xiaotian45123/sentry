import PropTypes from 'prop-types';
import React from 'react';
import createReactClass from 'create-react-class';
import Reflux from 'reflux';
import {Flex, Box} from 'grid-emotion';

import withApi from 'app/utils/withApi';
import IndicatorStore from 'app/stores/indicatorStore';
import DropdownLink from 'app/components/dropdownLink';
import SnoozeAction from 'app/components/issues/snoozeAction';
import GroupChart from 'app/components/stream/groupChart';
import GroupStore from 'app/stores/groupStore';
import Link from 'app/components/links/link';
import {t} from 'app/locale';
import {PanelItem} from 'app/components/panels';
import SentryTypes from 'app/sentryTypes';
import withOrganization from 'app/utils/withOrganization';

class CompactIssueHeader extends React.Component {
  static propTypes = {
    organization: SentryTypes.Organization.isRequired,
    projectId: PropTypes.string,
    eventId: PropTypes.string,
    data: PropTypes.object.isRequired,
  };

  getTitle = () => {
    const data = this.props.data;
    const metadata = data.metadata;
    switch (data.type) {
      case 'error':
        return (
          <span>
            <span style={{marginRight: 10}}>{metadata.type}</span>
            <em>{data.culprit}</em>
            <br />
          </span>
        );
      case 'csp':
        return (
          <span>
            <span style={{marginRight: 10}}>{metadata.directive}</span>
            <em>{metadata.uri}</em>
            <br />
          </span>
        );
      case 'default':
        return <span>{metadata.title}</span>;
      default:
        return <span>{data.title}</span>;
    }
  };

  getMessage = () => {
    const data = this.props.data;
    const metadata = data.metadata;
    switch (data.type) {
      case 'error':
        return metadata.value;
      case 'csp':
        return metadata.message;
      default:
        return '';
    }
  };

  render() {
    const {data, organization, projectId, eventId} = this.props;

    let styles = {};

    const basePath = `/organizations/${organization.slug}/issues/`;

    const issueLink = eventId
      ? `/organizations/${organization.slug}/projects/${projectId}/events/${eventId}/`
      : `${basePath}${data.id}/`;

    if (data.subscriptionDetails && data.subscriptionDetails.reason === 'mentioned') {
      styles = {color: '#57be8c'};
    }

    return (
      <React.Fragment>
        <Flex align="center">
          <Box mr={1}>
            <span className="error-level truncate" title={data.level} />
          </Box>
          <h3 className="truncate">
            <Link to={issueLink}>
              <span className="icon icon-soundoff" />
              <span className="icon icon-star-solid" />
              {this.getTitle()}
            </Link>
          </h3>
        </Flex>
        <div className="event-extra">
          <span className="project-name">
            <strong>{data.project.slug}</strong>
          </span>
          {data.numComments !== 0 && (
            <span>
              <Link to={`${basePath}${data.id}/activity/`} className="comments">
                <span className="icon icon-comments" style={styles} />
                <span className="tag-count">{data.numComments}</span>
              </Link>
            </span>
          )}
          <span className="culprit">{this.getMessage()}</span>
        </div>
      </React.Fragment>
    );
  }
}

const CompactIssue = createReactClass({
  displayName: 'CompactIssue',

  propTypes: {
    api: PropTypes.object,
    data: PropTypes.object,
    id: PropTypes.string,
    eventId: PropTypes.string,
    statsPeriod: PropTypes.string,
    showActions: PropTypes.bool,
    organization: SentryTypes.Organization.isRequired,
  },

  mixins: [Reflux.listenTo(GroupStore, 'onGroupChange')],

  getInitialState() {
    return {
      issue: this.props.data || GroupStore.get(this.props.id),
    };
  },

  componentWillReceiveProps(nextProps) {
    if (nextProps.id !== this.props.id) {
      this.setState({
        issue: GroupStore.get(this.props.id),
      });
    }
  },

  onGroupChange(itemIds) {
    if (!itemIds.has(this.props.id)) {
      return;
    }
    const id = this.props.id;
    const issue = GroupStore.get(id);
    this.setState({
      issue,
    });
  },

  onSnooze(duration) {
    const data = {
      status: 'ignored',
    };

    if (duration) {
      data.ignoreDuration = duration;
    }

    this.onUpdate(data);
  },

  onUpdate(data) {
    const issue = this.state.issue;
    const loadingIndicator = IndicatorStore.add(t('Saving changes..'));

    this.props.api.bulkUpdate(
      {
        orgId: this.props.organization.slug,
        projectId: issue.project.slug,
        itemIds: [issue.id],
        data,
      },
      {
        complete: () => {
          IndicatorStore.remove(loadingIndicator);
        },
      }
    );
  },

  render() {
    const issue = this.state.issue;
    const {id, organization} = this.props;

    let className = 'issue';
    if (issue.isBookmarked) {
      className += ' isBookmarked';
    }
    if (issue.hasSeen) {
      className += ' hasSeen';
    }
    if (issue.status === 'resolved') {
      className += ' isResolved';
    }
    if (issue.status === 'ignored') {
      className += ' isIgnored';
    }

    className += ' level-' + issue.level;

    if (this.props.statsPeriod) {
      className += ' with-graph';
    }

    const title = <span className="icon-more" />;

    return (
      <PanelItem
        className={className}
        onClick={this.toggleSelect}
        direction="column"
        style={{paddingTop: '12px', paddingBottom: '6px'}}
      >
        <CompactIssueHeader
          data={issue}
          organization={organization}
          projectId={issue.project.slug}
          eventId={this.props.eventId}
        />
        {this.props.statsPeriod && (
          <div className="event-graph">
            <GroupChart
              id={id}
              statsPeriod={this.props.statsPeriod}
              data={this.props.data}
            />
          </div>
        )}
        {this.props.showActions && (
          <div className="more-menu-container align-right">
            <DropdownLink
              topLevelClasses="more-menu"
              className="more-menu-toggle"
              caret={false}
              title={title}
            >
              <li>
                <a
                  onClick={this.onUpdate.bind(this, {
                    status: issue.status !== 'resolved' ? 'resolved' : 'unresolved',
                  })}
                >
                  <span className="icon-checkmark" />
                </a>
              </li>
              <li>
                <a
                  onClick={this.onUpdate.bind(this, {isBookmarked: !issue.isBookmarked})}
                >
                  <span className="icon-star-solid" />
                </a>
              </li>
              <li>
                <SnoozeAction
                  orgId={organization.slug}
                  groupId={id}
                  onSnooze={this.onSnooze}
                />
              </li>
            </DropdownLink>
          </div>
        )}
        {this.props.children}
      </PanelItem>
    );
  },
});

export {CompactIssue};
export default withApi(withOrganization(CompactIssue));

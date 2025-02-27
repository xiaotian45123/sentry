import PropTypes from 'prop-types';
import React from 'react';
import {isEqual} from 'lodash';

import SentryTypes from 'app/sentryTypes';
import Button from 'app/components/button';
import {t} from 'app/locale';
import InlineSvg from 'app/components/inlineSvg';

import QueryFields from './queryFields';
import {parseSavedQuery} from '../utils';
import {
  ButtonSpinner,
  QueryActions,
  QueryActionsGroup,
  SavedQueryAction,
} from '../styles';

export default class EditSavedQuery extends React.Component {
  static propTypes = {
    queryBuilder: PropTypes.object.isRequired,
    onRunQuery: PropTypes.func.isRequired,
    savedQuery: SentryTypes.DiscoverSavedQuery,
    onUpdateField: PropTypes.func.isRequired,
    onDeleteQuery: PropTypes.func.isRequired,
    onSaveQuery: PropTypes.func.isRequired,
    isFetchingQuery: PropTypes.bool.isRequired,
    isLoading: PropTypes.bool.isRequired,
  };

  constructor(props) {
    super(props);
    this.state = {
      savedQueryName: props.savedQuery.name,
    };
  }

  handleUpdateName(savedQueryName) {
    this.setState({savedQueryName});
  }

  hasChanges() {
    const {queryBuilder, savedQuery} = this.props;

    const hasChanged =
      !isEqual(parseSavedQuery(savedQuery), queryBuilder.getInternal()) ||
      this.state.savedQueryName !== savedQuery.name;
    return hasChanged;
  }

  render() {
    const {
      queryBuilder,
      savedQuery,
      isFetchingQuery,
      onUpdateField,
      onRunQuery,
      onDeleteQuery,
      onSaveQuery,
      isLoading,
    } = this.props;

    const {savedQueryName} = this.state;

    return (
      <QueryFields
        queryBuilder={queryBuilder}
        onUpdateField={onUpdateField}
        isLoading={isLoading}
        savedQuery={savedQuery}
        savedQueryName={this.state.savedQueryName}
        onUpdateName={name => this.handleUpdateName(name)}
        actions={
          <QueryActions>
            <QueryActionsGroup>
              <div>
                <Button
                  size="xsmall"
                  onClick={onRunQuery}
                  priority="primary"
                  busy={isFetchingQuery}
                >
                  {t('Run')}
                  {isFetchingQuery && <ButtonSpinner />}
                </Button>
              </div>
              <div>
                <Button
                  size="xsmall"
                  onClick={() => onSaveQuery(savedQueryName)}
                  disabled={!this.hasChanges()}
                >
                  {t('Save')}
                </Button>
              </div>
            </QueryActionsGroup>
            <div>
              <SavedQueryAction data-test-id="delete" onClick={onDeleteQuery}>
                <InlineSvg src="icon-trash" />
              </SavedQueryAction>
            </div>
          </QueryActions>
        }
      />
    );
  }
}

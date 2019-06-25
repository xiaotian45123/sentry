import React from 'react';

import {t} from 'app/locale';
import {openDebugFileSourceModal} from 'app/actionCreators/modal';

// Export route to make these forms searchable by label/help
export const route = '/settings/:orgId/projects/:projectId/debug-symbols/';

export const sourceNames = {
  gcs: t('Google Cloud Storage'),
  http: t('SymbolServer (HTTP)'),
  s3: t('Amazon S3'),
};

export function getSourceName(type) {
  return sourceNames[type] || t('Unknown');
}

export const fields = {
  builtinSymbolSources: {
    name: 'builtinSymbolSources',
    type: 'select',
    multiple: true,
    label: t('Built-in Repositories'),
    help: t(
      'Configures which built-in repositories Sentry should use to resolve debug files.'
    ),
    choices: ({builtinSymbolSources}) =>
      builtinSymbolSources &&
      builtinSymbolSources.map(source => [source.sentry_key, t(source.name)]),
  },
  symbolSources: {
    name: 'symbolSources',
    type: 'rich_list',
    label: t('Custom Repositories'),
    help: t(
      'Configures custom repositories containing debug files. At the moment, only Amazon S3 buckets are supported.'
    ),
    addButtonText: t('Add Repository'),
    addDropdown: {
      items: [
        {
          value: 's3',
          label: sourceNames.s3,
          searchKey: t('aws amazon s3 bucket'),
        },
        {
          value: 'gcs',
          label: sourceNames.gcs,
          searchKey: t('gcs google cloud storage bucket'),
        },
        {
          value: 'http',
          label: sourceNames.http,
          searchKey: t('http symbol server ssqp symstore symsrv'),
        },
      ],
    },

    renderItem(item) {
      if (item.name) {
        return item.name;
      } else {
        return <em>{t('<Unnamed Repository>')}</em>;
      }
    },

    onAddItem(item, addItem) {
      openDebugFileSourceModal({
        sourceType: item.value,
        onSave: addItem,
      });
    },

    onEditItem(item, updateItem) {
      openDebugFileSourceModal({
        sourceConfig: item,
        sourceType: item.type,
        onSave: updateItem,
      });
    },
  },
};

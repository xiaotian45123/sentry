/*eslint-env node*/
module.exports = {
  presets: ['@babel/react', '@babel/env'],
  plugins: [
    'emotion',
    'lodash',
    'react-hot-loader/babel',
    '@babel/plugin-syntax-dynamic-import',
    '@babel/plugin-proposal-object-rest-spread',
    '@babel/plugin-transform-runtime',
    // NOTE: The order of the decorator and class-property plugins is important
    // here. Decorators must be processed first before class properties, see:
    // https://babeljs.io/docs/en/plugins#plugin-ordering
    ['@babel/plugin-proposal-decorators', {legacy: true}],
    ['@babel/plugin-proposal-class-properties', {loose: true}],
  ],
  env: {
    production: {},
    development: {
      plugins: [
        ['emotion', {sourceMap: true, autoLabel: true}],
        '@babel/plugin-transform-react-jsx-source',
      ],
    },
    test: {
      plugins: [['emotion', {autoLabel: true}], 'dynamic-import-node'],
    },
  },
};

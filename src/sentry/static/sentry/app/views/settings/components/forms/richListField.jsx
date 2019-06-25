import PropTypes from 'prop-types';
import React from 'react';
import styled from 'react-emotion';

import {t} from 'app/locale';
import DropdownAutoComplete from 'app/components/dropdownAutoComplete';
import DropdownButton from 'app/components/dropdownButton';
import InputField from 'app/views/settings/components/forms/inputField';
import InlineSvg from 'app/components/inlineSvg';

export default class RichListField extends React.Component {
  static propTypes = {
    ...InputField.propTypes,

    /**
     * Text used for the add item button.
     */
    addButtonText: PropTypes.node,

    /**
     * Configuration for the add item dropdown.
     */
    addDropdown: PropTypes.shape(DropdownAutoComplete.propTypes).isRequired,

    /**
     * Render function to render an item.
     */
    renderItem: PropTypes.func,

    /**
     * Callback invoked when an item is added via the dropdown menu.
     */
    onAddItem: PropTypes.func,

    /**
     * Callback invoked when an item is interacted with.
     */
    onEditItem: PropTypes.func,

    /**
     * Callback invoked when an item is removed.
     */
    onRemoveItem: PropTypes.func,
  };

  static defaultProps = {
    addButtonText: t('Add Item'),
    renderItem: item => item,
    onAddItem: (item, addItem) => addItem(item),
    onEditItem: () => {},
    onRemoveItem: (item, removeItem) => removeItem(item),
  };

  parseItems = value => {
    return JSON.parse(value);
  };

  serializeItems = items => {
    return JSON.stringify(items);
  };

  hasItems = value => {
    return Array.isArray(value) && value.length > 0;
  };

  onAddItem = item => {
    const {onAddItem} = this.props;
    onAddItem(item, this.addItem);
  };

  handleChange = (items, onChange) => {
    onChange(this.serializeItems(items), new Event('onListChange'));
  };

  renderDropdown = (items, onChange) => {
    const {addButtonText, addDropdown} = this.props;

    const onAdd = data => {
      const complete = [...items, data];
      return this.handleChange(complete, onChange);
    };

    return (
      <DropdownAutoComplete
        {...addDropdown}
        alignMenu="left"
        onSelect={item => this.props.onAddItem(item, onAdd)}
      >
        {({isOpen}) => (
          <DropdownButton icon="icon-circle-add" isOpen={isOpen} size="small">
            {addButtonText}
          </DropdownButton>
        )}
      </DropdownAutoComplete>
    );
  };

  renderItem = (item, items, onChange) => {
    const {renderItem} = this.props;
    const index = items.indexOf(item);

    const onUpdate = data => {
      const complete = [...items];
      complete.splice(index, 1, data);
      return this.handleChange(complete, onChange);
    };

    const onRemove = () => {
      const complete = [...items];
      complete.splice(index, 1);
      return this.handleChange(complete, onChange);
    };

    return (
      <Item size="small" key={index}>
        <ItemLabel>
          {renderItem(item)}
          <ItemIcon onClick={() => this.props.onEditItem(item, onUpdate)}>
            <InlineSvg src="icon-edit" size="12px" />
          </ItemIcon>
          <ItemIcon onClick={() => this.props.onRemoveItem(item, onRemove)}>
            <InlineSvg src="icon-trash" size="12px" />
          </ItemIcon>
        </ItemLabel>
      </Item>
    );
  };

  renderField = props => {
    const {value, onChange} = props; // InputField props

    const items = this.parseItems(value);
    const hasItems = this.hasItems(items);

    return (
      <ItemList>
        {hasItems && items.map(item => this.renderItem(item, items, onChange))}
        {this.renderDropdown(items, onChange)}
      </ItemList>
    );
  };

  render() {
    return <InputField {...this.props} field={this.renderField} />;
  }
}

const ItemList = styled('div')`
  display: flex;
`;

const Item = styled('span')`
  display: inline-block;
  background-color: ${p => p.theme.button.default.background};
  border: 1px solid ${p => p.theme.button.default.border};
  border-radius: ${p => p.theme.button.borderRadius};
  color: ${p => p.theme.button.default.color};
  cursor: default;
  font-size: ${p => p.theme.fontSizeSmall};
  font-weight: 600;
  line-height: 1;
  padding: 0;
  text-transform: none;

  margin-right: 10px;
`;

const ItemLabel = styled('span')`
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 8px 12px;
`;

const ItemIcon = styled('span')`
  padding-left: 10px;
  color: ${p => p.theme.gray2};
  cursor: pointer;

  &:hover {
    color: ${p => p.theme.button.default.color};
  }
`;

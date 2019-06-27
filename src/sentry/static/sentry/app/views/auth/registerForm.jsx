import {browserHistory} from 'react-router';
import PropTypes from 'prop-types';
import React from 'react';

import {t, tct} from 'app/locale';
import ConfigStore from 'app/stores/configStore';
import Form from 'app/components/forms/form';
import PasswordField from 'app/components/forms/passwordField';
import TextField from 'app/components/forms/textField';
import RadioBooleanField from 'app/components/forms/radioBooleanField';

class AuthRegisterForm extends React.Component {
  static propTypes = {
    api: PropTypes.object,
    hasNewsletter: PropTypes.bool,
  };

  state = {
    errorMessage: null,
    errors: {},
  };

  handleSubmit = async (data, onSuccess, onError) => {
    const {api} = this.props;

    // Coerce to string int as that's what the backend wants.
    data.subscribe = data.subscribe ? '1' : '0';

    try {
      const response = await api.requestPromise('/auth/register/', {
        method: 'POST',
        data,
      });
      onSuccess(data);

      // TODO(epurkhiser): There is more we need to do to setup the user. but
      // definitely primarily we need to init our user.
      ConfigStore.set('user', response.user);

      browserHistory.push({pathname: response.nextUri});
    } catch (e) {
      if (!e.responseJSON) {
        onError(e);
        return;
      }
      let message = e.responseJSON.detail;
      if (e.responseJSON.errors.__all__) {
        message = e.responseJSON.errors.__all__;
      }
      this.setState({
        errorMessage: message,
        errors: e.responseJSON.errors || {},
      });
      onError(e);
    }
  };

  renderSubscribe() {
    return (
      <RadioBooleanField
        name="subscribe"
        yesLabel={t('Yes, I would like to receive updates via email')}
        noLabel={t("No, I'd prefer not to receive these updates")}
        help={tct(
          "We'd love to keep you updated via email with product and feature announcements, promotions, educational materials, and events. Our updates focus on relevant information, and we'll never sell your data to third parties. See our [link] for more details.",
          {
            link: <a href="https://sentry.io/privacy/">Privacy Policy</a>,
          }
        )}
      />
    );
  }

  render() {
    const {hasNewsletter} = this.props;
    const {errorMessage, errors} = this.state;

    return (
      <div className="tab-pane active" id="register">
        <div className="auth-container">
          <div className="auth-form-column">
            <Form
              initialData={{subscribe: true}}
              submitLabel={t('Continue')}
              onSubmit={this.handleSubmit}
              footerClass="auth-footer"
              errorMessage={errorMessage}
              extraButton={
                <a
                  href="https://sentry.io/privacy/"
                  rel="noopener noreferrer"
                  target="_blank"
                  className="secondary"
                >
                  {t('Privacy Policy')}
                </a>
              }
            >
              <TextField
                name="name"
                placeholder={t('Jane Doe')}
                maxlength={30}
                label={t('Name')}
                error={errors.name}
                required
              />
              <TextField
                name="username"
                placeholder={t('you@example.com')}
                maxlength={128}
                label={t('Email')}
                error={errors.username}
                required
              />
              <PasswordField
                name="password"
                placeholder={t('something super secret')}
                label={t('Password')}
                error={errors.password}
                required
              />
              {hasNewsletter && this.renderSubscribe()}
            </Form>
          </div>
        </div>
      </div>
    );
  }
}
export default AuthRegisterForm;

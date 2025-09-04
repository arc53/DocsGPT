import { useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import userService from '../api/services/userService';
import Dropdown from '../components/Dropdown';
import Input from '../components/Input';
import Spinner from '../components/Spinner';
import { useOutsideAlerter } from '../hooks';
import { ActiveState } from '../models/misc';
import { selectToken } from '../preferences/preferenceSlice';
import WrapperComponent from './WrapperModal';

interface MCPServerModalProps {
  modalState: ActiveState;
  setModalState: (state: ActiveState) => void;
  server?: any;
  onServerSaved: () => void;
}

const authTypes = [
  { label: 'No Authentication', value: 'none' },
  { label: 'API Key', value: 'api_key' },
  { label: 'Bearer Token', value: 'bearer' },
  // { label: 'Basic Authentication', value: 'basic' },
];

export default function MCPServerModal({
  modalState,
  setModalState,
  server,
  onServerSaved,
}: MCPServerModalProps) {
  const { t } = useTranslation();
  const token = useSelector(selectToken);
  const modalRef = useRef<HTMLDivElement>(null);

  const [formData, setFormData] = useState({
    name: server?.displayName || 'My MCP Server',
    server_url: server?.server_url || '',
    auth_type: server?.auth_type || 'none',
    api_key: '',
    header_name: 'X-API-Key',
    bearer_token: '',
    username: '',
    password: '',
    timeout: server?.timeout || 30,
  });

  const [loading, setLoading] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{
    success: boolean;
    message: string;
  } | null>(null);
  const [errors, setErrors] = useState<{ [key: string]: string }>({});

  useOutsideAlerter(modalRef, () => {
    if (modalState === 'ACTIVE') {
      setModalState('INACTIVE');
      resetForm();
    }
  }, [modalState]);

  const resetForm = () => {
    setFormData({
      name: 'My MCP Server',
      server_url: '',
      auth_type: 'none',
      api_key: '',
      header_name: 'X-API-Key',
      bearer_token: '',
      username: '',
      password: '',
      timeout: 30,
    });
    setErrors({});
    setTestResult(null);
  };

  const validateForm = () => {
    const requiredFields: { [key: string]: boolean } = {
      name: !formData.name.trim(),
      server_url: !formData.server_url.trim(),
    };

    const authFieldChecks: { [key: string]: () => void } = {
      api_key: () => {
        if (!formData.api_key.trim())
          newErrors.api_key = t('settings.tools.mcp.errors.apiKeyRequired');
      },
      bearer: () => {
        if (!formData.bearer_token.trim())
          newErrors.bearer_token = t('settings.tools.mcp.errors.tokenRequired');
      },
      basic: () => {
        if (!formData.username.trim())
          newErrors.username = t('settings.tools.mcp.errors.usernameRequired');
        if (!formData.password.trim())
          newErrors.password = t('settings.tools.mcp.errors.passwordRequired');
      },
    };

    const newErrors: { [key: string]: string } = {};
    Object.entries(requiredFields).forEach(([field, isEmpty]) => {
      if (isEmpty)
        newErrors[field] = t(
          `settings.tools.mcp.errors.${field === 'name' ? 'nameRequired' : 'urlRequired'}`,
        );
    });

    if (formData.server_url.trim()) {
      try {
        new URL(formData.server_url);
      } catch {
        newErrors.server_url = t('settings.tools.mcp.errors.invalidUrl');
      }
    }

    const timeoutValue = formData.timeout === '' ? 30 : formData.timeout;
    if (
      typeof timeoutValue === 'number' &&
      (timeoutValue < 1 || timeoutValue > 300)
    )
      newErrors.timeout = 'Timeout must be between 1 and 300 seconds';

    if (authFieldChecks[formData.auth_type])
      authFieldChecks[formData.auth_type]();

    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const handleInputChange = (name: string, value: string | number) => {
    setFormData((prev) => ({ ...prev, [name]: value }));
    if (errors[name]) {
      setErrors((prev) => ({ ...prev, [name]: '' }));
    }
    setTestResult(null);
  };

  const buildToolConfig = () => {
    const config: any = {
      server_url: formData.server_url.trim(),
      auth_type: formData.auth_type,
      timeout: formData.timeout === '' ? 30 : formData.timeout,
    };

    if (formData.auth_type === 'api_key') {
      config.api_key = formData.api_key.trim();
      config.api_key_header = formData.header_name.trim() || 'X-API-Key';
    } else if (formData.auth_type === 'bearer') {
      config.bearer_token = formData.bearer_token.trim();
    } else if (formData.auth_type === 'basic') {
      config.username = formData.username.trim();
      config.password = formData.password.trim();
    }
    return config;
  };

  const testConnection = async () => {
    if (!validateForm()) return;
    setTesting(true);
    setTestResult(null);
    try {
      const config = buildToolConfig();
      const response = await userService.testMCPConnection({ config }, token);
      const result = await response.json();

      setTestResult(result);
    } catch (error) {
      setTestResult({
        success: false,
        message: t('settings.tools.mcp.errors.testFailed'),
      });
    } finally {
      setTesting(false);
    }
  };

  const handleSave = async () => {
    if (!validateForm()) return;
    setLoading(true);
    try {
      const config = buildToolConfig();
      const serverData = {
        displayName: formData.name,
        config,
        status: true,
        ...(server?.id && { id: server.id }),
      };

      const response = await userService.saveMCPServer(serverData, token);
      const result = await response.json();

      if (response.ok && result.success) {
        setTestResult({
          success: true,
          message: result.message,
        });
        onServerSaved();
        setModalState('INACTIVE');
        resetForm();
      } else {
        setErrors({
          general: result.error || t('settings.tools.mcp.errors.saveFailed'),
        });
      }
    } catch (error) {
      console.error('Error saving MCP server:', error);
      setErrors({ general: t('settings.tools.mcp.errors.saveFailed') });
    } finally {
      setLoading(false);
    }
  };

  const renderAuthFields = () => {
    switch (formData.auth_type) {
      case 'api_key':
        return (
          <div className="mb-10">
            <div className="mt-6">
              <Input
                name="api_key"
                type="text"
                className="rounded-md"
                value={formData.api_key}
                onChange={(e) => handleInputChange('api_key', e.target.value)}
                placeholder={t('settings.tools.mcp.placeholders.apiKey')}
                borderVariant="thin"
                labelBgClassName="bg-white dark:bg-charleston-green-2"
              />
              {errors.api_key && (
                <p className="mt-1 text-sm text-red-600">{errors.api_key}</p>
              )}
            </div>
            <div className="mt-5">
              <Input
                name="header_name"
                type="text"
                className="rounded-md"
                value={formData.header_name}
                onChange={(e) =>
                  handleInputChange('header_name', e.target.value)
                }
                placeholder={t('settings.tools.mcp.headerName')}
                borderVariant="thin"
                labelBgClassName="bg-white dark:bg-charleston-green-2"
              />
            </div>
          </div>
        );
      case 'bearer':
        return (
          <div className="mb-10">
            <Input
              name="bearer_token"
              type="text"
              className="rounded-md"
              value={formData.bearer_token}
              onChange={(e) =>
                handleInputChange('bearer_token', e.target.value)
              }
              placeholder={t('settings.tools.mcp.placeholders.bearerToken')}
              borderVariant="thin"
              labelBgClassName="bg-white dark:bg-charleston-green-2"
            />
            {errors.bearer_token && (
              <p className="mt-1 text-sm text-red-600">{errors.bearer_token}</p>
            )}
          </div>
        );
      case 'basic':
        return (
          <div className="mb-10">
            <div className="mt-6">
              <Input
                name="username"
                type="text"
                className="rounded-md"
                value={formData.username}
                onChange={(e) => handleInputChange('username', e.target.value)}
                placeholder={t('settings.tools.mcp.username')}
                borderVariant="thin"
                labelBgClassName="bg-white dark:bg-charleston-green-2"
              />
              {errors.username && (
                <p className="mt-1 text-sm text-red-600">{errors.username}</p>
              )}
            </div>
            <div className="mt-5">
              <Input
                name="password"
                type="text"
                className="rounded-md"
                value={formData.password}
                onChange={(e) => handleInputChange('password', e.target.value)}
                placeholder={t('settings.tools.mcp.password')}
                borderVariant="thin"
                labelBgClassName="bg-white dark:bg-charleston-green-2"
              />
              {errors.password && (
                <p className="mt-1 text-sm text-red-600">{errors.password}</p>
              )}
            </div>
          </div>
        );
      default:
        return null;
    }
  };

  return (
    modalState === 'ACTIVE' && (
      <WrapperComponent
        close={() => {
          setModalState('INACTIVE');
          resetForm();
        }}
        className="max-w-[600px] md:w-[80vw] lg:w-[60vw]"
      >
        <div className="flex h-full flex-col">
          <div className="px-6 py-4">
            <h2 className="text-jet dark:text-bright-gray text-xl font-semibold">
              {server
                ? t('settings.tools.mcp.editServer')
                : t('settings.tools.mcp.addServer')}
            </h2>
          </div>
          <div className="flex-1 px-6">
            <div className="space-y-6 py-6">
              <div>
                <Input
                  name="name"
                  type="text"
                  className="rounded-md"
                  value={formData.name}
                  onChange={(e) => handleInputChange('name', e.target.value)}
                  borderVariant="thin"
                  placeholder={t('settings.tools.mcp.serverName')}
                  labelBgClassName="bg-white dark:bg-charleston-green-2"
                />
                {errors.name && (
                  <p className="mt-1 text-sm text-red-600">{errors.name}</p>
                )}
              </div>

              <div>
                <Input
                  name="server_url"
                  type="text"
                  className="rounded-md"
                  value={formData.server_url}
                  onChange={(e) =>
                    handleInputChange('server_url', e.target.value)
                  }
                  placeholder={t('settings.tools.mcp.serverUrl')}
                  borderVariant="thin"
                  labelBgClassName="bg-white dark:bg-charleston-green-2"
                />
                {errors.server_url && (
                  <p className="mt-1 text-sm text-red-600">
                    {errors.server_url}
                  </p>
                )}
              </div>

              <Dropdown
                placeholder={t('settings.tools.mcp.authType')}
                selectedValue={
                  authTypes.find((type) => type.value === formData.auth_type)
                    ?.label || null
                }
                onSelect={(selection: { label: string; value: string }) => {
                  handleInputChange('auth_type', selection.value);
                }}
                options={authTypes}
                size="w-full"
                rounded="3xl"
                border="border"
              />

              {renderAuthFields()}

              <div>
                <Input
                  name="timeout"
                  type="number"
                  className="rounded-md"
                  value={formData.timeout}
                  onChange={(e) => {
                    const value = e.target.value;
                    if (value === '') {
                      handleInputChange('timeout', '');
                    } else {
                      const numValue = parseInt(value);
                      if (!isNaN(numValue) && numValue >= 1) {
                        handleInputChange('timeout', numValue);
                      }
                    }
                  }}
                  placeholder={t('settings.tools.mcp.timeout')}
                  borderVariant="thin"
                  labelBgClassName="bg-white dark:bg-charleston-green-2"
                />
                {errors.timeout && (
                  <p className="mt-2 text-sm text-red-600">{errors.timeout}</p>
                )}
              </div>

              {testResult && (
                <div
                  className={`rounded-md p-5 ${
                    testResult.success
                      ? 'bg-green-50 text-green-700 dark:bg-green-900/40 dark:text-green-300'
                      : 'bg-red-50 text-red-700 dark:bg-red-900 dark:text-red-300'
                  }`}
                >
                  {testResult.message}
                </div>
              )}
              {errors.general && (
                <div className="rounded-2xl bg-red-50 p-5 text-red-700 dark:bg-red-900 dark:text-red-300">
                  {errors.general}
                </div>
              )}
            </div>
          </div>

          <div className="px-6 py-2">
            <div className="flex flex-col gap-4 sm:flex-row sm:justify-between">
              <button
                onClick={testConnection}
                disabled={testing}
                className="border-silver dark:border-dim-gray dark:text-light-gray w-full rounded-3xl border px-6 py-2 text-sm font-medium transition-all hover:bg-gray-100 disabled:opacity-50 sm:w-auto dark:hover:bg-[#767183]/50"
              >
                {testing ? (
                  <div className="flex items-center justify-center">
                    <Spinner size="small" />
                    <span className="ml-2">
                      {t('settings.tools.mcp.testing')}
                    </span>
                  </div>
                ) : (
                  t('settings.tools.mcp.testConnection')
                )}
              </button>

              <div className="flex flex-col-reverse gap-3 sm:flex-row sm:gap-3">
                <button
                  onClick={() => {
                    setModalState('INACTIVE');
                    resetForm();
                  }}
                  className="dark:text-light-gray w-full cursor-pointer rounded-3xl px-6 py-2 text-sm font-medium hover:bg-gray-100 sm:w-auto dark:bg-transparent dark:hover:bg-[#767183]/50"
                >
                  {t('settings.tools.mcp.cancel')}
                </button>
                <button
                  onClick={handleSave}
                  disabled={loading}
                  className="bg-purple-30 hover:bg-violets-are-blue w-full rounded-3xl px-6 py-2 text-sm font-medium text-white transition-all disabled:opacity-50 sm:w-auto"
                >
                  {loading ? (
                    <div className="flex items-center justify-center">
                      <Spinner size="small" />
                      <span className="ml-2">
                        {t('settings.tools.mcp.saving')}
                      </span>
                    </div>
                  ) : (
                    t('settings.tools.mcp.save')
                  )}
                </button>
              </div>
            </div>
          </div>
        </div>
      </WrapperComponent>
    )
  );
}

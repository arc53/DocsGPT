import { useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import apiClient from '../api/client';
import userService from '../api/services/userService';
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
  { value: 'none', label: 'No Authentication' },
  { value: 'api_key', label: 'API Key' },
  { value: 'bearer', label: 'Bearer Token' },
  { value: 'basic', label: 'Basic Authentication' },
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
    name: server?.name || 'My MCP Server',
    server_url: server?.server_url || '',
    auth_type: server?.auth_type || 'none',
    api_key: '',
    header_name: 'X-API-Key',
    bearer_token: '',
    username: '',
    password: '',
    timeout: 30,
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
    const newErrors: { [key: string]: string } = {};

    if (!formData.name.trim()) {
      newErrors.name = t('settings.tools.mcp.errors.nameRequired');
    }

    if (!formData.server_url.trim()) {
      newErrors.server_url = t('settings.tools.mcp.errors.urlRequired');
    } else {
      try {
        new URL(formData.server_url);
      } catch {
        newErrors.server_url = t('settings.tools.mcp.errors.invalidUrl');
      }
    }

    if (formData.auth_type === 'api_key' && !formData.api_key.trim()) {
      newErrors.api_key = t('settings.tools.mcp.errors.apiKeyRequired');
    }

    if (formData.auth_type === 'bearer' && !formData.bearer_token.trim()) {
      newErrors.bearer_token = t('settings.tools.mcp.errors.tokenRequired');
    }

    if (formData.auth_type === 'basic') {
      if (!formData.username.trim()) {
        newErrors.username = t('settings.tools.mcp.errors.usernameRequired');
      }
      if (!formData.password.trim()) {
        newErrors.password = t('settings.tools.mcp.errors.passwordRequired');
      }
    }

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
      timeout: formData.timeout,
    };

    // Add credentials directly to config for encryption
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
      // Create a temporary tool to test
      const config = buildToolConfig();

      const testData = {
        name: 'mcp_tool',
        displayName: formData.name,
        description: 'MCP Server Connection',
        config,
        actions: [],
        status: false,
      };

      const response = await userService.createTool(testData, token);
      const result = await response.json();

      if (response.ok && result.id) {
        // Test the connection
        try {
          const testResponse = await apiClient.post(
            `/api/mcp_server/${result.id}/test`,
            {},
            token,
          );
          const testData = await testResponse.json();
          setTestResult(testData);

          // Clean up the temporary tool
          await userService.deleteTool({ id: result.id }, token);
        } catch (error) {
          setTestResult({
            success: false,
            message: t('settings.tools.mcp.errors.testFailed'),
          });
          // Clean up the temporary tool
          await userService.deleteTool({ id: result.id }, token);
        }
      } else {
        setTestResult({
          success: false,
          message: t('settings.tools.mcp.errors.testFailed'),
        });
      }
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

      const toolData = {
        name: 'mcp_tool',
        displayName: formData.name,
        description: `MCP Server: ${formData.server_url}`,
        config,
        actions: [], // Will be populated after tool creation
        status: true,
      };

      let toolId: string;

      if (server) {
        // Update existing server
        await userService.updateTool({ id: server.id, ...toolData }, token);
        toolId = server.id;
      } else {
        // Create new server
        const response = await userService.createTool(toolData, token);
        const result = await response.json();
        toolId = result.id;
      }

      // Now fetch the MCP tools and update the actions
      try {
        const toolsResponse = await apiClient.get(
          `/api/mcp_server/${toolId}/tools`,
          token,
        );

        if (toolsResponse.success && toolsResponse.actions) {
          // Update the tool with discovered actions (already formatted by backend)
          await userService.updateTool(
            {
              id: toolId,
              ...toolData,
              actions: toolsResponse.actions,
            },
            token,
          );

          console.log(
            `Successfully discovered and saved ${toolsResponse.actions.length} MCP tools`,
          );

          // Show success message with tool count
          setTestResult({
            success: true,
            message: `MCP server saved successfully! Discovered ${toolsResponse.actions.length} tools.`,
          });
        }
      } catch (error) {
        console.warn(
          'Warning: Could not fetch MCP tools immediately after creation:',
          error,
        );
        // Don't fail the save operation if tool discovery fails
      }

      onServerSaved();
      setModalState('INACTIVE');
      resetForm();
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
          <div className="space-y-4">
            <div>
              <label className="mb-2 block text-sm font-medium text-gray-700 dark:text-gray-300">
                {t('settings.tools.mcp.apiKey')}
              </label>
              <Input
                name="api_key"
                type="text"
                value={formData.api_key}
                onChange={(e) => handleInputChange('api_key', e.target.value)}
                placeholder={t('settings.tools.mcp.placeholders.apiKey')}
              />
              {errors.api_key && (
                <p className="mt-1 text-sm text-red-600">{errors.api_key}</p>
              )}
            </div>
            <div>
              <label className="mb-2 block text-sm font-medium text-gray-700 dark:text-gray-300">
                {t('settings.tools.mcp.headerName')}
              </label>
              <Input
                name="header_name"
                type="text"
                value={formData.header_name}
                onChange={(e) =>
                  handleInputChange('header_name', e.target.value)
                }
                placeholder="X-API-Key"
              />
            </div>
          </div>
        );
      case 'bearer':
        return (
          <div>
            <label className="mb-2 block text-sm font-medium text-gray-700 dark:text-gray-300">
              {t('settings.tools.mcp.bearerToken')}
            </label>
            <Input
              name="bearer_token"
              type="text"
              value={formData.bearer_token}
              onChange={(e) =>
                handleInputChange('bearer_token', e.target.value)
              }
              placeholder={t('settings.tools.mcp.placeholders.bearerToken')}
            />
            {errors.bearer_token && (
              <p className="mt-1 text-sm text-red-600">{errors.bearer_token}</p>
            )}
          </div>
        );
      case 'basic':
        return (
          <div className="space-y-4">
            <div>
              <label className="mb-2 block text-sm font-medium text-gray-700 dark:text-gray-300">
                {t('settings.tools.mcp.username')}
              </label>
              <Input
                name="username"
                type="text"
                value={formData.username}
                onChange={(e) => handleInputChange('username', e.target.value)}
                placeholder={t('settings.tools.mcp.placeholders.username')}
              />
              {errors.username && (
                <p className="mt-1 text-sm text-red-600">{errors.username}</p>
              )}
            </div>
            <div>
              <label className="mb-2 block text-sm font-medium text-gray-700 dark:text-gray-300">
                {t('settings.tools.mcp.password')}
              </label>
              <Input
                name="password"
                type="text"
                value={formData.password}
                onChange={(e) => handleInputChange('password', e.target.value)}
                placeholder={t('settings.tools.mcp.placeholders.password')}
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

          <div className="flex-1 overflow-auto px-6">
            <div className="space-y-6">
              <div>
                <Input
                  name="name"
                  type="text"
                  value={formData.name}
                  onChange={(e) => handleInputChange('name', e.target.value)}
                  borderVariant="thin"
                  placeholder={t('settings.tools.mcp.placeholders.serverName')}
                  labelBgClassName="bg-white dark:bg-charleston-green-2"
                />
                {errors.name && (
                  <p className="mt-1 text-sm text-red-600">{errors.name}</p>
                )}
              </div>

              <div>
                <label className="mb-2 block text-sm font-medium text-gray-700 dark:text-gray-300">
                  {t('settings.tools.mcp.serverUrl')}
                </label>
                <Input
                  name="server_url"
                  type="text"
                  value={formData.server_url}
                  onChange={(e) =>
                    handleInputChange('server_url', e.target.value)
                  }
                  placeholder={t('settings.tools.mcp.placeholders.serverUrl')}
                />
                {errors.server_url && (
                  <p className="mt-1 text-sm text-red-600">
                    {errors.server_url}
                  </p>
                )}
              </div>

              <div>
                <label className="mb-2 block text-sm font-medium text-gray-700 dark:text-gray-300">
                  {t('settings.tools.mcp.authType')}
                </label>
                <select
                  value={formData.auth_type}
                  onChange={(e) =>
                    handleInputChange('auth_type', e.target.value)
                  }
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 dark:border-gray-600 dark:bg-gray-700 dark:text-white"
                >
                  {authTypes.map((type) => (
                    <option key={type.value} value={type.value}>
                      {type.label}
                    </option>
                  ))}
                </select>
              </div>

              {renderAuthFields()}

              <div>
                <label className="mb-2 block text-sm font-medium text-gray-700 dark:text-gray-300">
                  {t('settings.tools.mcp.timeout')}
                </label>
                <Input
                  name="timeout"
                  type="number"
                  value={formData.timeout}
                  onChange={(e) =>
                    handleInputChange('timeout', parseInt(e.target.value) || 30)
                  }
                  placeholder="30"
                />
              </div>

              {testResult && (
                <div
                  className={`rounded-lg p-4 ${
                    testResult.success
                      ? 'bg-green-50 text-green-700 dark:bg-green-900 dark:text-green-300'
                      : 'bg-red-50 text-red-700 dark:bg-red-900 dark:text-red-300'
                  }`}
                >
                  {testResult.message}
                </div>
              )}

              {errors.general && (
                <div className="rounded-lg bg-red-50 p-4 text-red-700 dark:bg-red-900 dark:text-red-300">
                  {errors.general}
                </div>
              )}
            </div>
          </div>

          <div className="flex justify-between gap-4 px-6 py-4">
            <button
              onClick={testConnection}
              disabled={testing}
              className="flex items-center justify-center rounded-lg border border-gray-300 px-4 py-2 text-gray-700 hover:bg-gray-50 disabled:opacity-50 dark:border-gray-600 dark:text-gray-300 dark:hover:bg-gray-700"
            >
              {testing ? (
                <div className="flex items-center">
                  <Spinner />
                  <span className="ml-2">
                    {t('settings.tools.mcp.testing')}
                  </span>
                </div>
              ) : (
                t('settings.tools.mcp.testConnection')
              )}
            </button>

            <div className="flex gap-2">
              <button
                onClick={() => {
                  setModalState('INACTIVE');
                  resetForm();
                }}
                className="px-4 py-2 text-gray-600 hover:text-gray-800 dark:text-gray-400 dark:hover:text-gray-200"
              >
                {t('settings.tools.mcp.cancel')}
              </button>
              <button
                onClick={handleSave}
                disabled={loading}
                className="bg-purple-30 hover:bg-violets-are-blue flex items-center justify-center rounded-lg px-6 py-2 text-white disabled:opacity-50"
              >
                {loading ? (
                  <div className="flex items-center">
                    <Spinner />
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
      </WrapperComponent>
    )
  );
}

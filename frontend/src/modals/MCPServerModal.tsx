import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import { baseURL } from '../api/client';
import userService from '../api/services/userService';
import Spinner from '../components/Spinner';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../components/ui/select';
import { ActiveState } from '../models/misc';
import { selectRecentEvents } from '../notifications/notificationsSlice';
import { selectToken } from '../preferences/preferenceSlice';
import WrapperComponent from './WrapperModal';

interface MCPServerModalProps {
  modalState: ActiveState;
  setModalState: (state: ActiveState) => void;
  server?: any;
  onServerSaved: () => void;
}

export default function MCPServerModal({
  modalState,
  setModalState,
  server,
  onServerSaved,
}: MCPServerModalProps) {
  const { t } = useTranslation();
  const token = useSelector(selectToken);
  const recentEvents = useSelector(selectRecentEvents);

  const authTypes = [
    { label: t('settings.tools.mcp.authTypes.none'), value: 'none' },
    { label: t('settings.tools.mcp.authTypes.apiKey'), value: 'api_key' },
    { label: t('settings.tools.mcp.authTypes.bearer'), value: 'bearer' },
    { label: t('settings.tools.mcp.authTypes.oauth'), value: 'oauth' },
    // { label: t('settings.tools.mcp.authTypes.basic'), value: 'basic' },
  ];

  const [formData, setFormData] = useState({
    name: server?.displayName || t('settings.tools.mcp.defaultServerName'),
    server_url: server?.server_url || '',
    auth_type: server?.auth_type || 'none',
    api_key: '',
    header_name: server?.api_key_header || 'X-API-Key',
    bearer_token: '',
    username: '',
    password: '',
    timeout: server?.timeout || 30,
    oauth_scopes: server?.oauth_scopes || '',
    oauth_task_id: '',
  });

  const [loading, setLoading] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{
    success: boolean;
    message: string;
    status?: string;
    authorization_url?: string;
    tools?: { name: string; description?: string }[];
    tools_count?: number;
  } | null>(null);
  const [discoveredTools, setDiscoveredTools] = useState<
    { name: string; description?: string }[]
  >([]);
  const [errors, setErrors] = useState<{ [key: string]: string }>({});
  const oauthPopupRef = useRef<Window | null>(null);
  // Set after ``test_mcp_connection`` returns ``task_id``. The SSE
  // effect filters ``recentEvents`` to envelopes matching this id and
  // drives the OAuth UI (popup open / completion / failure) from the
  // push stream rather than polling the legacy status endpoint.
  const [oauthTaskId, setOauthTaskId] = useState<string | null>(null);
  // Highest event id we have already reacted to for this taskId. Each
  // mcp.oauth.* envelope must fire its side-effect once; without this
  // any later re-render that re-evaluates ``recentEvents`` would
  // re-open the popup or re-fire onComplete.
  const handledEventIdsRef = useRef<Set<string>>(new Set());
  // Holds the ``testConnection`` ``onComplete`` for the current
  // task id so the SSE effect can invoke it when the terminal event
  // lands. Reset to ``null`` on cancel / new test / unmount.
  const onCompleteRef = useRef<((result: any) => void) | null>(null);
  const popupOpenedRef = useRef(false);
  const [oauthCompleted, setOAuthCompleted] = useState(false);
  const [saveActive, setSaveActive] = useState(false);

  const cleanupOAuthListener = useCallback(() => {
    setOauthTaskId(null);
    handledEventIdsRef.current = new Set();
    onCompleteRef.current = null;
    popupOpenedRef.current = false;
    if (oauthPopupRef.current && !oauthPopupRef.current.closed) {
      oauthPopupRef.current.close();
    }
    oauthPopupRef.current = null;
  }, []);

  useEffect(() => {
    return cleanupOAuthListener;
  }, [cleanupOAuthListener]);

  useEffect(() => {
    if (modalState === 'ACTIVE' && server) {
      const oauthScopes = Array.isArray(server.oauth_scopes)
        ? server.oauth_scopes.join(', ')
        : server.oauth_scopes || '';
      setFormData({
        name: server.displayName || t('settings.tools.mcp.defaultServerName'),
        server_url: server.server_url || '',
        auth_type: server.auth_type || 'none',
        api_key: '',
        header_name: server.api_key_header || 'X-API-Key',
        bearer_token: '',
        username: '',
        password: '',
        timeout: server.timeout || 30,
        oauth_scopes: oauthScopes,
        oauth_task_id: '',
      });
      setErrors({});
      setTestResult(null);
      setDiscoveredTools([]);
      setSaveActive(false);
      setOAuthCompleted(false);
    }
  }, [modalState, server]);

  const resetForm = () => {
    cleanupOAuthListener();
    setFormData({
      name: t('settings.tools.mcp.defaultServerName'),
      server_url: '',
      auth_type: 'none',
      api_key: '',
      header_name: 'X-API-Key',
      bearer_token: '',
      username: '',
      password: '',
      timeout: 30,
      oauth_scopes: '',
      oauth_task_id: '',
    });
    setErrors({});
    setTestResult(null);
    setDiscoveredTools([]);
    setSaveActive(false);
    setTesting(false);
    setOAuthCompleted(false);
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
      newErrors.timeout = t('settings.tools.mcp.errors.timeoutRange');

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
    } else if (formData.auth_type === 'oauth') {
      config.oauth_scopes = formData.oauth_scopes
        .split(',')
        .map((s: string) => s.trim())
        .filter(Boolean);
      config.oauth_task_id = formData.oauth_task_id.trim();
      config.redirect_uri = `${baseURL.replace(/\/$/, '')}/api/mcp_server/callback`;
    }
    return config;
  };

  /**
   * Drive the OAuth handshake straight from the SSE stream:
   *
   * - ``mcp.oauth.awaiting_redirect`` → open the popup with the
   *   ``authorization_url`` carried on the envelope. Previously this URL
   *   came from polling ``/api/mcp_server/oauth_status/<task_id>``; the
   *   worker now publishes it inline so we never need to poll.
   * - ``mcp.oauth.completed`` → enable Save, surface discovered tools,
   *   invoke ``onComplete`` (resolves ``testConnection``'s pending state).
   * - ``mcp.oauth.failed`` → surface the error and reset Save.
   *
   * Each event is matched to the active task id via ``scope.id``. The
   * publisher is best-effort: a lost ``awaiting_redirect`` envelope
   * means the popup never opens, the user retries, and we accept that
   * over the prior 1s × 60 polling loop.
   */
  useEffect(() => {
    if (!oauthTaskId) return;
    // ``recentEvents`` is newest-first (the slice ``unshift``s on
    // arrival). Walk it oldest-first so we observe the natural OAuth
    // ordering (``awaiting_redirect`` → ``completed``) when both
    // arrive between effect runs — otherwise we would short-circuit
    // on ``completed`` and never open the popup for the
    // ``awaiting_redirect`` envelope that was already buffered.
    for (let i = recentEvents.length - 1; i >= 0; i--) {
      const event = recentEvents[i];
      if (event.scope?.id !== oauthTaskId) continue;
      if (!event.id || handledEventIdsRef.current.has(event.id)) continue;

      const payload = (event.payload || {}) as Record<string, unknown>;

      if (event.type === 'mcp.oauth.awaiting_redirect') {
        handledEventIdsRef.current.add(event.id);
        const authUrl = payload.authorization_url as string | undefined;
        if (authUrl && !popupOpenedRef.current) {
          popupOpenedRef.current = true;
          if (oauthPopupRef.current && !oauthPopupRef.current.closed) {
            oauthPopupRef.current.close();
          }
          oauthPopupRef.current = window.open(
            authUrl,
            'oauthPopup',
            'width=600,height=700',
          );
          if (!oauthPopupRef.current) {
            // Popup blocked — surface the URL inline so the user can
            // click through manually. Browsers gate ``window.open``
            // outside of a user gesture, and the SSE event arrives
            // asynchronously, so a blocked popup is expected on
            // some browsers / configs.
            setTestResult({
              success: true,
              message: t('settings.tools.mcp.oauthPopupBlocked', {
                defaultValue:
                  'Popup blocked by browser. Click below to authorize:',
              }),
              authorization_url: authUrl,
            });
          }
        }
        continue;
      }

      if (event.type === 'mcp.oauth.completed') {
        handledEventIdsRef.current.add(event.id);
        const tools = Array.isArray(payload.tools) ? payload.tools : [];
        const toolsCount =
          (payload.tools_count as number | undefined) ?? tools.length;
        setOAuthCompleted(true);
        setSaveActive(true);
        if (oauthPopupRef.current && !oauthPopupRef.current.closed) {
          oauthPopupRef.current.close();
        }
        const cb = onCompleteRef.current;
        onCompleteRef.current = null;
        setOauthTaskId(null);
        if (cb) {
          cb({
            status: 'completed',
            task_id: oauthTaskId,
            tools,
            tools_count: toolsCount,
            success: true,
            message: t('settings.tools.mcp.oauthCompleted'),
          });
        }
        continue;
      }

      if (event.type === 'mcp.oauth.failed') {
        handledEventIdsRef.current.add(event.id);
        const message =
          (payload.error as string) ??
          t('settings.tools.mcp.errors.oauthFailed');
        setSaveActive(false);
        if (oauthPopupRef.current && !oauthPopupRef.current.closed) {
          oauthPopupRef.current.close();
        }
        const cb = onCompleteRef.current;
        onCompleteRef.current = null;
        setOauthTaskId(null);
        if (cb) {
          cb({
            status: 'error',
            task_id: oauthTaskId,
            success: false,
            message,
          });
        }
        continue;
      }
    }
  }, [recentEvents, oauthTaskId, t]);

  const testConnection = async () => {
    if (!validateForm()) return;
    cleanupOAuthListener();
    setTesting(true);
    setTestResult(null);
    setDiscoveredTools([]);
    setOAuthCompleted(false);
    try {
      const config = buildToolConfig();
      const response = await userService.testMCPConnection({ config }, token);
      const result = await response.json();

      if (
        formData.auth_type === 'oauth' &&
        result.requires_oauth &&
        result.task_id
      ) {
        setTestResult({
          success: true,
          message: t('settings.tools.mcp.oauthInProgress'),
        });
        setSaveActive(false);
        onCompleteRef.current = (finalResult: any) => {
          setTestResult(finalResult);
          if (finalResult.tools && Array.isArray(finalResult.tools)) {
            setDiscoveredTools(finalResult.tools);
          }
          setFormData((prev) => ({
            ...prev,
            oauth_task_id: result.task_id || '',
          }));
          setTesting(false);
        };
        // Activate the SSE listener for this task id. The effect above
        // will react when ``mcp.oauth.{awaiting_redirect,completed,failed}``
        // arrives.
        setOauthTaskId(result.task_id);
      } else {
        setTestResult(result);
        if (result.success && result.tools && Array.isArray(result.tools)) {
          setDiscoveredTools(result.tools);
        }
        setSaveActive(result.success === true);
        setTesting(false);
      }
    } catch (error) {
      setTestResult({
        success: false,
        message: t('settings.tools.mcp.errors.testFailed'),
      });
      setOAuthCompleted(false);
      setSaveActive(false);
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
    } catch {
      setErrors({ general: t('settings.tools.mcp.errors.saveFailed') });
    } finally {
      setLoading(false);
    }
  };

  const renderAuthFields = () => {
    switch (formData.auth_type) {
      case 'api_key':
        return (
          <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="api_key">
                {t('settings.tools.mcp.placeholders.apiKey')}
                <span className="text-red-500">*</span>
              </Label>
              <Input
                id="api_key"
                type="text"
                value={formData.api_key}
                onChange={(e) => handleInputChange('api_key', e.target.value)}
                placeholder={t('settings.tools.mcp.placeholders.apiKey')}
                aria-invalid={!!errors.api_key || undefined}
                className="rounded-xl"
              />
              {errors.api_key && (
                <p className="text-destructive text-xs">{errors.api_key}</p>
              )}
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="header_name">
                {t('settings.tools.mcp.headerName')}
              </Label>
              <Input
                id="header_name"
                type="text"
                value={formData.header_name}
                onChange={(e) =>
                  handleInputChange('header_name', e.target.value)
                }
                placeholder="X-API-Key"
                className="rounded-xl"
              />
            </div>
          </div>
        );
      case 'bearer':
        return (
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="bearer_token">
              {t('settings.tools.mcp.placeholders.bearerToken')}
              <span className="text-red-500">*</span>
            </Label>
            <Input
              id="bearer_token"
              type="text"
              value={formData.bearer_token}
              onChange={(e) =>
                handleInputChange('bearer_token', e.target.value)
              }
              placeholder={t('settings.tools.mcp.placeholders.bearerToken')}
              aria-invalid={!!errors.bearer_token || undefined}
              className="rounded-xl"
            />
            {errors.bearer_token && (
              <p className="text-destructive text-xs">{errors.bearer_token}</p>
            )}
          </div>
        );
      case 'basic':
        return (
          <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="username">
                {t('settings.tools.mcp.username')}
                <span className="text-red-500">*</span>
              </Label>
              <Input
                id="username"
                type="text"
                value={formData.username}
                onChange={(e) => handleInputChange('username', e.target.value)}
                placeholder={t('settings.tools.mcp.username')}
                aria-invalid={!!errors.username || undefined}
                className="rounded-xl"
              />
              {errors.username && (
                <p className="text-destructive text-xs">{errors.username}</p>
              )}
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="password">
                {t('settings.tools.mcp.password')}
                <span className="text-red-500">*</span>
              </Label>
              <Input
                id="password"
                type="password"
                value={formData.password}
                onChange={(e) => handleInputChange('password', e.target.value)}
                placeholder={t('settings.tools.mcp.password')}
                aria-invalid={!!errors.password || undefined}
                className="rounded-xl"
              />
              {errors.password && (
                <p className="text-destructive text-xs">{errors.password}</p>
              )}
            </div>
          </div>
        );
      case 'oauth':
        return (
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="oauth_scopes">
              {t('settings.tools.mcp.placeholders.oauthScopes') ||
                'Scopes (comma separated)'}
            </Label>
            <Input
              id="oauth_scopes"
              type="text"
              value={formData.oauth_scopes}
              onChange={(e) =>
                handleInputChange('oauth_scopes', e.target.value)
              }
              placeholder="read, write"
              className="rounded-xl"
            />
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
            <h2 className="text-foreground dark:text-foreground text-xl font-semibold">
              {server
                ? t('settings.tools.mcp.reconnectServer', {
                    defaultValue: 'Reconnect Server',
                  })
                : t('settings.tools.mcp.addServer')}
            </h2>
          </div>
          <div className="flex-1 px-6">
            <div className="flex flex-col gap-4 px-0.5 py-4">
              {server?.has_encrypted_credentials &&
                formData.auth_type !== 'oauth' && (
                  <div className="rounded-xl bg-amber-50 p-3 text-sm text-amber-700 dark:bg-amber-900/30 dark:text-amber-300">
                    {t('settings.tools.mcp.reenterCredentials', {
                      defaultValue:
                        'Re-enter your credentials to test and update the connection.',
                    })}
                  </div>
                )}
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="mcp-name">
                  {t('settings.tools.mcp.serverName')}
                  <span className="text-red-500">*</span>
                </Label>
                <Input
                  id="mcp-name"
                  type="text"
                  value={formData.name}
                  onChange={(e) => handleInputChange('name', e.target.value)}
                  placeholder={t('settings.tools.mcp.serverName')}
                  aria-invalid={!!errors.name || undefined}
                  className="rounded-xl"
                />
                {errors.name && (
                  <p className="text-destructive text-xs">{errors.name}</p>
                )}
              </div>

              <div className="flex flex-col gap-1.5">
                <Label htmlFor="mcp-url">
                  {t('settings.tools.mcp.serverUrl')}
                  <span className="text-red-500">*</span>
                </Label>
                <Input
                  id="mcp-url"
                  type="text"
                  value={formData.server_url}
                  onChange={(e) =>
                    handleInputChange('server_url', e.target.value)
                  }
                  placeholder="https://example.com/mcp"
                  aria-invalid={!!errors.server_url || undefined}
                  className="rounded-xl"
                />
                {errors.server_url && (
                  <p className="text-destructive text-xs">
                    {errors.server_url}
                  </p>
                )}
              </div>

              <div className="flex flex-col gap-1.5">
                <Label>{t('settings.tools.mcp.authType')}</Label>
                <Select
                  value={formData.auth_type}
                  onValueChange={(v) => handleInputChange('auth_type', v)}
                >
                  <SelectTrigger
                    variant="ghost"
                    size="lg"
                    className="w-full rounded-xl"
                  >
                    <SelectValue
                      placeholder={t('settings.tools.mcp.authType')}
                    />
                  </SelectTrigger>
                  <SelectContent>
                    {authTypes.map((type) => (
                      <SelectItem key={type.value} value={type.value}>
                        {type.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              {renderAuthFields()}

              <div className="flex flex-col gap-1.5">
                <Label htmlFor="mcp-timeout">
                  {t('settings.tools.mcp.timeout')}
                </Label>
                <Input
                  id="mcp-timeout"
                  type="number"
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
                  placeholder="30"
                  min={1}
                  max={300}
                  aria-invalid={!!errors.timeout || undefined}
                  className="rounded-xl"
                />
                {errors.timeout && (
                  <p className="text-destructive text-xs">{errors.timeout}</p>
                )}
              </div>

              {testResult && (
                <div
                  className={`rounded-xl p-4 text-sm ${
                    testResult.success
                      ? 'bg-green-50 text-green-700 dark:bg-green-900/40 dark:text-green-300'
                      : 'bg-red-50 text-red-700 dark:bg-red-900/40 dark:text-red-300'
                  }`}
                >
                  <p>{testResult.message}</p>
                  {testResult.authorization_url && (
                    <a
                      href={testResult.authorization_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      onClick={(e) => {
                        e.preventDefault();
                        const popup = window.open(
                          testResult.authorization_url,
                          'oauthPopup',
                          'width=600,height=700',
                        );
                        if (popup) oauthPopupRef.current = popup;
                      }}
                      className="mt-1.5 inline-block font-medium underline"
                    >
                      {t('settings.tools.mcp.openAuthPage', {
                        defaultValue: 'Open authorization page',
                      })}
                    </a>
                  )}
                </div>
              )}

              {discoveredTools.length > 0 && testResult?.success && (
                <div className="border-border dark:border-border rounded-xl border p-4">
                  <h4 className="mb-2 text-sm font-medium text-gray-900 dark:text-white">
                    {t('settings.tools.mcp.discoveredTools', {
                      count: discoveredTools.length,
                      defaultValue: `Discovered Actions (${discoveredTools.length})`,
                    })}
                  </h4>
                  <ul className="flex max-h-40 flex-col gap-1.5 overflow-y-auto">
                    {discoveredTools.map((tool) => (
                      <li
                        key={tool.name}
                        className="flex items-start gap-2 rounded-lg bg-gray-50 px-3 py-2 text-sm dark:bg-white/5"
                      >
                        <span className="text-primary mt-0.5">&#9679;</span>
                        <div className="min-w-0">
                          <span className="font-medium text-gray-900 dark:text-white">
                            {tool.name}
                          </span>
                          {tool.description && (
                            <p className="truncate text-xs text-gray-500 dark:text-gray-400">
                              {tool.description}
                            </p>
                          )}
                        </div>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {errors.general && (
                <div className="rounded-xl bg-red-50 p-4 text-sm text-red-700 dark:bg-red-900/40 dark:text-red-300">
                  {errors.general}
                </div>
              )}
            </div>
          </div>

          <div className="px-6 py-4">
            <div className="flex flex-col gap-3 sm:flex-row sm:justify-between">
              <button
                onClick={testConnection}
                disabled={testing}
                className="border-border dark:border-border dark:text-foreground hover:bg-accent dark:hover:bg-muted/50 w-full rounded-3xl border px-6 py-2 text-sm font-medium transition-all disabled:opacity-50 sm:w-auto"
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
                  className="dark:text-foreground hover:bg-accent dark:hover:bg-muted/50 w-full cursor-pointer rounded-3xl px-6 py-2 text-sm font-medium sm:w-auto"
                >
                  {t('settings.tools.mcp.cancel')}
                </button>
                <button
                  onClick={handleSave}
                  disabled={loading || !saveActive}
                  className="bg-primary hover:bg-primary/90 w-full rounded-3xl px-6 py-2 text-sm font-medium text-white transition-all disabled:opacity-50 sm:w-auto"
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

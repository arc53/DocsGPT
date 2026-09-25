import { CircleAlert, CircleCheck, TriangleAlert } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import { baseURL } from '../api/client';
import userService from '../api/services/userService';
import { Alert, AlertDescription } from '../components/ui/alert';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { FormField } from '../components/ui/form-field';
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
import { Modal, ModalActions } from '../components/ui/modal';

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
            <FormField
              label={t('settings.tools.mcp.authTypes.apiKey')}
              required
              error={errors.api_key}
            >
              <Input
                id="api_key"
                type="text"
                value={formData.api_key}
                onChange={(e) => handleInputChange('api_key', e.target.value)}
                placeholder={t('settings.tools.mcp.placeholders.apiKey')}
              />
            </FormField>
            <FormField label={t('settings.tools.mcp.headerName')}>
              <Input
                id="header_name"
                type="text"
                value={formData.header_name}
                onChange={(e) =>
                  handleInputChange('header_name', e.target.value)
                }
                placeholder="X-API-Key"
              />
            </FormField>
          </div>
        );
      case 'bearer':
        return (
          <FormField
            label={t('settings.tools.mcp.authTypes.bearer')}
            required
            error={errors.bearer_token}
          >
            <Input
              id="bearer_token"
              type="text"
              value={formData.bearer_token}
              onChange={(e) =>
                handleInputChange('bearer_token', e.target.value)
              }
              placeholder={t('settings.tools.mcp.placeholders.bearerToken')}
            />
          </FormField>
        );
      case 'basic':
        return (
          <div className="flex flex-col gap-4">
            <FormField
              label={t('settings.tools.mcp.username')}
              required
              error={errors.username}
            >
              <Input
                id="username"
                type="text"
                value={formData.username}
                onChange={(e) => handleInputChange('username', e.target.value)}
                placeholder={t('settings.tools.mcp.placeholders.username')}
              />
            </FormField>
            <FormField
              label={t('settings.tools.mcp.password')}
              required
              error={errors.password}
            >
              <Input
                id="password"
                type="password"
                value={formData.password}
                onChange={(e) => handleInputChange('password', e.target.value)}
                placeholder={t('settings.tools.mcp.placeholders.password')}
              />
            </FormField>
          </div>
        );
      case 'oauth':
        return (
          <FormField label={t('settings.tools.mcp.placeholders.oauthScopes')}>
            <Input
              id="oauth_scopes"
              type="text"
              value={formData.oauth_scopes}
              onChange={(e) =>
                handleInputChange('oauth_scopes', e.target.value)
              }
              placeholder="read, write"
            />
          </FormField>
        );
      default:
        return null;
    }
  };

  return (
    <Modal
      open={modalState === 'ACTIVE'}
      onOpenChange={(o) => {
        if (!o) {
          setModalState('INACTIVE');
          resetForm();
        }
      }}
      title={
        server
          ? t('settings.tools.mcp.reconnectServer', {
              defaultValue: 'Reconnect Server',
            })
          : t('settings.tools.mcp.addServer')
      }
      size="lg"
      mobileVariant="sheet"
      className="max-w-[600px] md:w-[80vw] lg:w-[60vw]"
      footer={
        <ModalActions
          footerStart={
            <Button
              type="button"
              variant="outline"
              onClick={testConnection}
              loading={testing}
              size="lg"
              shape="pill"
            >
              {t('settings.tools.mcp.testConnection')}
            </Button>
          }
          cancelLabel={t('settings.tools.mcp.cancel')}
          onCancel={() => {
            setModalState('INACTIVE');
            resetForm();
          }}
          submitLabel={t('settings.tools.mcp.save')}
          onSubmit={handleSave}
          pending={loading}
          disabled={!saveActive}
        />
      }
    >
      <div className="flex flex-col gap-4 px-0.5 py-4">
        {server?.has_encrypted_credentials &&
          formData.auth_type !== 'oauth' && (
            <Alert variant="warning">
              <TriangleAlert className="size-4" aria-hidden="true" />
              <AlertDescription>
                {t('settings.tools.mcp.reenterCredentials', {
                  defaultValue:
                    'Re-enter your credentials to test and update the connection.',
                })}
              </AlertDescription>
            </Alert>
          )}
        <FormField
          label={t('settings.tools.mcp.serverName')}
          required
          error={errors.name}
        >
          <Input
            id="mcp-name"
            type="text"
            value={formData.name}
            onChange={(e) => handleInputChange('name', e.target.value)}
            placeholder={t('settings.tools.mcp.serverName')}
          />
        </FormField>

        <FormField
          label={t('settings.tools.mcp.serverUrl')}
          required
          error={errors.server_url}
        >
          <Input
            id="mcp-url"
            type="text"
            value={formData.server_url}
            onChange={(e) => handleInputChange('server_url', e.target.value)}
            placeholder="https://example.com/mcp"
          />
        </FormField>

        <FormField label={t('settings.tools.mcp.authType')} id="mcp-auth-type">
          <Select
            value={formData.auth_type}
            onValueChange={(v) => handleInputChange('auth_type', v)}
          >
            <SelectTrigger variant="ghost" size="lg" className="w-full">
              <SelectValue placeholder={t('settings.tools.mcp.authType')} />
            </SelectTrigger>
            <SelectContent>
              {authTypes.map((type) => (
                <SelectItem key={type.value} value={type.value}>
                  {type.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FormField>

        {renderAuthFields()}

        <FormField
          label={t('settings.tools.mcp.timeout')}
          error={errors.timeout}
        >
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
          />
        </FormField>

        {testResult && (
          <Alert variant={testResult.success ? 'success' : 'destructive'}>
            {testResult.success ? (
              <CircleCheck className="size-4" aria-hidden="true" />
            ) : (
              <CircleAlert className="size-4" aria-hidden="true" />
            )}
            <AlertDescription>
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
            </AlertDescription>
          </Alert>
        )}

        {discoveredTools.length > 0 && testResult?.success && (
          <div className="border-border rounded-xl border p-4">
            <h4 className="text-foreground mb-2 text-sm font-medium">
              {t('settings.tools.mcp.discoveredTools', {
                count: discoveredTools.length,
                defaultValue: `Discovered Actions (${discoveredTools.length})`,
              })}
            </h4>
            <ul className="flex max-h-40 flex-col gap-1.5 overflow-y-auto">
              {discoveredTools.map((tool) => (
                <li
                  key={tool.name}
                  className="bg-muted flex items-start gap-2 rounded-lg px-3 py-2 text-sm"
                >
                  <span className="text-primary mt-0.5">&#9679;</span>
                  <div className="min-w-0">
                    <span className="text-foreground font-medium">
                      {tool.name}
                    </span>
                    {tool.description && (
                      <p className="text-muted-foreground truncate text-xs">
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
          <Alert variant="destructive">
            <CircleAlert className="size-4" aria-hidden="true" />
            <AlertDescription>{errors.general}</AlertDescription>
          </Alert>
        )}
      </div>
    </Modal>
  );
}

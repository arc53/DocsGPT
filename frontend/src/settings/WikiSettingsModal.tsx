import { CircleAlert } from 'lucide-react';
import { useEffect, useId, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import userService from '../api/services/userService';
import ViewOnlyNotice from '../components/ViewOnlyNotice';
import { Alert, AlertDescription } from '../components/ui/alert';
import { LoadingState } from '../components/ui/loading-state';
import { Modal } from '../components/ui/modal';
import { SettingRow, SettingRows } from '../components/ui/setting-row';
import { Switch } from '../components/ui/switch';
import { Doc } from '../models/misc';
import { selectToken } from '../preferences/preferenceSlice';
import { can } from '../utils/accessUtils';

type WikiSettings = {
  allow_outside_edits: boolean;
  allowed_actions?: string[];
};

interface WikiSettingsModalProps {
  document: Doc;
  onClose: () => void;
}

/**
 * A wiki's owner settings. Today one switch: whether people using an agent
 * through its API key, widget or public link may edit the wiki. It saves at
 * once and flips back when the server refuses.
 */
export default function WikiSettingsModal({
  document,
  onClose,
}: WikiSettingsModalProps) {
  const { t } = useTranslation();
  const token = useSelector(selectToken);
  const switchId = useId();

  const [settings, setSettings] = useState<WikiSettings | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveFailed, setSaveFailed] = useState(false);

  const sourceId = document.id ?? '';
  // Read through a ref: a token refresh is the same user and must not reload.
  const tokenRef = useRef(token);
  tokenRef.current = token;

  useEffect(() => {
    let cancelled = false;
    setSettings(null);
    setLoadFailed(false);
    userService
      .getWikiSettings(sourceId, tokenRef.current)
      .then(async (response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = (await response.json()) as WikiSettings;
        if (!cancelled) setSettings(data);
      })
      .catch(() => {
        if (!cancelled) setLoadFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [sourceId]);

  const canManage = can(settings, 'manage_settings');

  const toggle = async (value: boolean) => {
    if (!settings) return;
    const previous = settings;
    setSettings({ ...previous, allow_outside_edits: value });
    setSaving(true);
    setSaveFailed(false);
    try {
      const response = await userService.updateWikiSettings(
        sourceId,
        { allow_outside_edits: value },
        token,
      );
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = (await response.json()) as WikiSettings;
      setSettings(data);
    } catch {
      setSettings(previous);
      setSaveFailed(true);
    } finally {
      setSaving(false);
    }
  };

  const body = () => {
    if (loadFailed) {
      return (
        <Alert variant="destructive">
          <CircleAlert />
          <AlertDescription>
            {t('settings.sources.wiki.settings.loadError')}
          </AlertDescription>
        </Alert>
      );
    }
    if (!settings) return <LoadingState fill="block" />;
    return (
      <div className="flex flex-col gap-4">
        {!canManage && <ViewOnlyNotice />}
        {saveFailed && (
          <Alert variant="destructive">
            <CircleAlert />
            <AlertDescription>
              {t('settings.sources.wiki.settings.saveError')}
            </AlertDescription>
          </Alert>
        )}
        <SettingRows>
          <SettingRow
            htmlFor={switchId}
            alignStart
            label={t('settings.sources.wiki.settings.outsideEdits.label')}
            description={t(
              'settings.sources.wiki.settings.outsideEdits.description',
            )}
          >
            <Switch
              id={switchId}
              checked={settings.allow_outside_edits}
              disabled={!canManage || saving}
              onCheckedChange={toggle}
            />
          </SettingRow>
        </SettingRows>
      </div>
    );
  };

  return (
    <Modal
      open={true}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={t('settings.sources.wiki.settings.title')}
      description={document.name}
    >
      {body()}
    </Modal>
  );
}

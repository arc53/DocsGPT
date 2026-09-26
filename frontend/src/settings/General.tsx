import React from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';

import { Button } from '../components/ui/button';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../components/ui/select';
import { SectionHeader } from '../components/ui/section-header';
import { SettingRow, SettingRows } from '../components/ui/setting-row';
import PageToolbar from '../components/PageToolbar';
import { useDarkTheme } from '../hooks';
import {
  selectPrompt,
  selectPrompts,
  setModalStateDeleteConv,
  setPrompt,
  setPrompts,
} from '../preferences/preferenceSlice';
import Prompts from './Prompts';

export default function General() {
  const {
    t,
    i18n: { changeLanguage },
  } = useTranslation();
  const themes = [
    { value: 'Light', label: t('settings.general.light') },
    { value: 'Dark', label: t('settings.general.dark') },
  ];

  const languageOptions = [
    { label: 'English', value: 'en' },
    { label: 'Deutsch', value: 'de' },
    { label: 'Español', value: 'es' },
    { label: '日本語', value: 'jp' },
    { label: '普通话', value: 'zh' },
    { label: '繁體中文（臺灣）', value: 'zhTW' },
    { label: 'Русский', value: 'ru' },
  ];
  const prompts = useSelector(selectPrompts);
  const [isDarkTheme, toggleTheme] = useDarkTheme();
  const [selectedTheme, setSelectedTheme] = React.useState(
    isDarkTheme ? 'Dark' : 'Light',
  );
  const dispatch = useDispatch();
  const themeId = React.useId();
  const languageId = React.useId();
  const locale = localStorage.getItem('docsgpt-locale');
  // Fall back to English when the stored locale is not one we offer. Without
  // the fallback `find` returns undefined, the effect below writes the string
  // "undefined" into localStorage, and every subsequent load fails the same
  // lookup — the picker renders blank and can never recover.
  const [selectedLanguage, setSelectedLanguage] = React.useState(
    languageOptions.find((option) => option.value === locale) ??
      languageOptions[0],
  );
  const selectedPrompt = useSelector(selectPrompt);

  React.useEffect(() => {
    if (!selectedLanguage?.value) return;
    localStorage.setItem('docsgpt-locale', selectedLanguage.value);
    changeLanguage(selectedLanguage.value);
  }, [selectedLanguage, changeLanguage]);
  return (
    <div>
      <PageToolbar intro={t('settings.general.subtitle')} divider />
      <div className="flex max-w-3xl flex-col gap-10">
        <section className="flex flex-col gap-4">
          <SectionHeader title={t('settings.general.sections.appearance')} />
          <SettingRows>
            <SettingRow
              label={t('settings.general.theme')}
              description={t('settings.general.themeDescription')}
              htmlFor={themeId}
              stack
            >
              <Select
                value={selectedTheme}
                onValueChange={(value) => {
                  setSelectedTheme(value);
                  if (value !== selectedTheme) toggleTheme();
                }}
              >
                <SelectTrigger
                  id={themeId}
                  className="w-full sm:w-56"
                  size="field"
                  shape="pill"
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {themes.map((theme) => (
                    <SelectItem key={theme.value} value={theme.value}>
                      {theme.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </SettingRow>
            <SettingRow
              label={t('settings.general.language')}
              description={t('settings.general.languageDescription')}
              htmlFor={languageId}
              stack
            >
              <Select
                value={selectedLanguage?.value}
                onValueChange={(value) => {
                  const opt = languageOptions.find((o) => o.value === value);
                  if (opt) setSelectedLanguage(opt);
                }}
              >
                <SelectTrigger
                  id={languageId}
                  className="w-full sm:w-56"
                  size="field"
                  shape="pill"
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {languageOptions.map((opt) => (
                    <SelectItem key={opt.value} value={opt.value}>
                      {opt.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </SettingRow>
          </SettingRows>
        </section>
        <section className="flex flex-col gap-4">
          <SectionHeader title={t('settings.general.sections.chat')} />
          <SettingRows>
            <Prompts
              prompts={prompts}
              selectedPrompt={selectedPrompt}
              description={t('settings.general.promptDescription')}
              onSelectPrompt={(name, id, type) =>
                dispatch(setPrompt({ name: name, id: id, type: type }))
              }
              setPrompts={(newPrompts) => dispatch(setPrompts(newPrompts))}
            />
          </SettingRows>
        </section>
        <section className="flex flex-col gap-4">
          <SectionHeader
            title={t('settings.general.sections.dangerZone')}
            tone="destructive"
          />
          <SettingRows>
            <SettingRow
              label={t('settings.general.deleteAllLabel')}
              description={t('settings.general.deleteAllDescription')}
              as="h3"
            >
              <Button
                type="button"
                variant="destructive-outline"
                size="field"
                shape="pill"
                onClick={() => dispatch(setModalStateDeleteConv('ACTIVE'))}
              >
                {t('settings.general.deleteAllBtn')}
              </Button>
            </SettingRow>
          </SettingRows>
        </section>
      </div>
    </div>
  );
}

import React from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';

import userService from '../api/services/userService';
import Dropdown from '../components/Dropdown';
import { useDarkTheme } from '../hooks';
import {
  selectChunks,
  selectPrompt,
  selectProxy,
  selectToken,
  selectTokenLimit,
  setChunks,
  setModalStateDeleteConv,
  setPrompt,
  setProxy,
  setTokenLimit,
} from '../preferences/preferenceSlice';
import Prompts from './Prompts';
import Proxies from './Proxies';

export default function General() {
  const {
    t,
    i18n: { changeLanguage },
  } = useTranslation();
  const token = useSelector(selectToken);
  const themes = [
    { value: 'Light', label: t('settings.general.light') },
    { value: 'Dark', label: t('settings.general.dark') },
  ];

  const languageOptions = [
    { label: 'English', value: 'en' },
    { label: 'Español', value: 'es' },
    { label: '日本語', value: 'jp' },
    { label: '普通话', value: 'zh' },
    { label: '繁體中文（臺灣）', value: 'zhTW' },
    { label: 'Русский', value: 'ru' },
  ];
  const chunks = ['0', '2', '4', '6', '8', '10'];
  const token_limits = new Map([
    [0, t('settings.general.none')],
    [100, t('settings.general.low')],
    [1000, t('settings.general.medium')],
    [2000, t('settings.general.default')],
    [4000, t('settings.general.high')],
    [1e9, t('settings.general.unlimited')],
  ]);
  const [prompts, setPrompts] = React.useState<
    { name: string; id: string; type: string }[]
  >([]);
  const [proxies, setProxies] = React.useState<
    { name: string; id: string; type: string }[]
  >([]);
  const selectedChunks = useSelector(selectChunks);
  const selectedTokenLimit = useSelector(selectTokenLimit);
  const [isDarkTheme, toggleTheme] = useDarkTheme();
  const [selectedTheme, setSelectedTheme] = React.useState(
    isDarkTheme ? 'Dark' : 'Light',
  );
  const dispatch = useDispatch();
  const locale = localStorage.getItem('docsgpt-locale');
  const [selectedLanguage, setSelectedLanguage] = React.useState(
    locale
      ? languageOptions.find((option) => option.value === locale)
      : languageOptions[0],
  );
  const selectedPrompt = useSelector(selectPrompt);
  const selectedProxy = useSelector(selectProxy);

  React.useEffect(() => {
    // Set default proxy state first (only if no stored preference exists)
    const storedProxy = localStorage.getItem('DocsGPTProxy');
    if (!storedProxy) {
      const noneProxy = { name: 'None', id: 'none', type: 'public' };
      dispatch(setProxy(noneProxy));
    } else {
      try {
        const parsedProxy = JSON.parse(storedProxy);
        dispatch(setProxy(parsedProxy));
      } catch (e) {
        console.error('Error parsing stored proxy', e);
        // Fallback to None if parsing fails
        dispatch(setProxy({ name: 'None', id: 'none', type: 'public' }));
      }
    }
    // Fetch available proxies
    const handleFetchProxies = async () => {
      try {
        const response = await userService.getProxies(token);
        if (!response.ok) {
          console.warn('Proxies API not implemented yet or failed to fetch');
          return;
        }
        const proxiesData = await response.json();
        if (proxiesData && Array.isArray(proxiesData)) {
          // Filter out 'none' as we add it separately in the component
          const filteredProxies = proxiesData.filter((p) => p.id !== 'none');
          setProxies(filteredProxies);
        }
      } catch (error) {
        console.error('Error fetching proxies:', error);
      }
    };
    handleFetchProxies();
  }, [token, dispatch]);

  React.useEffect(() => {
    const handleFetchPrompts = async () => {
      try {
        const response = await userService.getPrompts(token);
        if (!response.ok) {
          throw new Error('Failed to fetch prompts');
        }
        const promptsData = await response.json();
        setPrompts(promptsData);
      } catch (error) {
        console.error(error);
      }
    };
    handleFetchPrompts();
  }, [token]);

  React.useEffect(() => {
    localStorage.setItem('docsgpt-locale', selectedLanguage?.value as string);
    changeLanguage(selectedLanguage?.value);
  }, [selectedLanguage, changeLanguage]);

  return (
    <div className="mt-12 flex flex-col gap-4">
      {' '}
      <div className="flex flex-col gap-4">
        {' '}
        <label className="font-medium text-base text-jet dark:text-bright-gray">
          {t('settings.general.selectTheme')}
        </label>
        <Dropdown
          options={themes}
          selectedValue={
            themes.find((theme) => theme.value === selectedTheme) || null
          }
          onSelect={(option: { value: string; label: string }) => {
            setSelectedTheme(option.value);
            option.value !== selectedTheme && toggleTheme();
          }}
          size="w-56"
          rounded="3xl"
          border="border"
        />
      </div>
      <div className="flex flex-col gap-4">
        <label className="font-medium text-base text-jet dark:text-bright-gray">
          {t('settings.general.selectLanguage')}
        </label>
        <Dropdown
          options={languageOptions.filter(
            (languageOption) =>
              languageOption.value !== selectedLanguage?.value,
          )}
          selectedValue={selectedLanguage ?? languageOptions[0]}
          onSelect={(selectedOption: { label: string; value: string }) => {
            setSelectedLanguage(selectedOption);
          }}
          size="w-56"
          rounded="3xl"
          border="border"
        />
      </div>
      <div className="flex flex-col gap-4">
        <label className="font-medium text-base text-jet dark:text-bright-gray">
          {t('settings.general.chunks')}
        </label>
        <Dropdown
          options={chunks}
          selectedValue={selectedChunks}
          onSelect={(value: string) => dispatch(setChunks(value))}
          size="w-56"
          rounded="3xl"
          border="border"
        />
      </div>
      <div className="flex flex-col gap-4">
        <label className="font-medium text-base text-jet dark:text-bright-gray">
          {t('settings.general.convHistory')}
        </label>
        <Dropdown
          options={Array.from(token_limits, ([value, desc]) => ({
            value: value,
            description: desc,
          }))}
          selectedValue={{
            value: selectedTokenLimit,
            description: token_limits.get(selectedTokenLimit) as string,
          }}
          onSelect={({
            value,
            description,
          }: {
            value: number;
            description: string;
          }) => dispatch(setTokenLimit(value))}
          size="w-56"
          rounded="3xl"
          border="border"
        />
      </div>
      <div className="flex flex-col gap-4">
        <Prompts
          prompts={prompts}
          selectedPrompt={selectedPrompt}
          onSelectPrompt={(name, id, type) =>
            dispatch(setPrompt({ name: name, id: id, type: type }))
          }
          setPrompts={setPrompts}
        />
      </div>
      <div className="flex flex-col gap-4">
        <Proxies
          proxies={proxies}
          selectedProxy={selectedProxy}
          onSelectProxy={(name, id, type) =>
            dispatch(setProxy({ name: name, id: id, type: type }))
          }
          setProxies={setProxies}
        />
      </div>
      <hr className="border-t w-[calc(min(665px,100%))] my-4 border-silver dark:border-silver/40" />
      <div className="flex flex-col gap-2">
        <button
          title={t('settings.general.deleteAllLabel')}
          className="flex font-medium text-sm w-fit cursor-pointer items-center justify-between rounded-3xl border border-solid border-rosso-corsa bg-transparent px-5 py-3 text-rosso-corsa transition-colors hover:bg-rosso-corsa hover:text-white hover:font-bold tracking-[0.015em] hover:tracking-normal"
          onClick={() => dispatch(setModalStateDeleteConv('ACTIVE'))}
        >
          {t('settings.general.deleteAllBtn')}
        </button>
      </div>
    </div>
  );
}

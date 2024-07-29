import React from 'react';
import { useTranslation } from 'react-i18next';

import Exit from '../assets/exit.svg';
import { SaveAPIKeyModalProps } from '../models/misc';

export default function SaveAPIKeyModal({
  apiKey,
  close,
}: SaveAPIKeyModalProps) {
  const { t } = useTranslation();
  const [isCopied, setIsCopied] = React.useState(false);

  const handleCopyKey = () => {
    navigator.clipboard.writeText(apiKey);
    setIsCopied(true);
  };
  return (
    <div className="fixed top-0 left-0 z-30 flex h-screen w-screen items-center justify-center bg-gray-alpha bg-opacity-50">
      <div className="relative w-11/12 rounded-3xl bg-white px-6 py-8 dark:bg-outer-space dark:text-bright-gray sm:w-[512px]">
        <button className="absolute top-3 right-4 m-2 w-3" onClick={close}>
          <img className="filter dark:invert" src={Exit} />
        </button>
        <h1 className="my-0 text-xl font-medium">
          {' '}
          {t('modals.saveKey.note')}
        </h1>
        <h3 className="text-sm font-normal text-outer-space">
          {t('modals.saveKey.disclaimer')}
        </h3>
        <div className="flex justify-between py-2">
          <div>
            <h2 className="text-base font-semibold">API Key</h2>
            <span className="text-sm font-normal leading-7 ">{apiKey}</span>
          </div>
          <button
            className="my-1 h-10 w-20 rounded-full border border-solid border-purple-30 p-2 text-sm text-purple-30 hover:bg-purple-30 hover:text-white"
            onClick={handleCopyKey}
          >
            {isCopied ? t('modals.saveKey.copied') : t('modals.saveKey.copy')}
          </button>
        </div>
        <button
          onClick={close}
          className="rounded-full bg-philippine-yellow px-4 py-3 font-medium text-black hover:bg-[#E6B91A]"
        >
          {t('modals.saveKey.confirm')}
        </button>
      </div>
    </div>
  );
}

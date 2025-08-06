import React from 'react';
import { useTranslation } from 'react-i18next';

import { SaveAPIKeyModalProps } from '../models/misc';
import WrapperModal from './WrapperModal';

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
    <WrapperModal close={close}>
      <h1 className="text-jet dark:text-bright-gray my-0 text-xl font-medium">
        {t('modals.saveKey.note')}
      </h1>
      <h3 className="text-outer-space dark:text-silver text-sm font-normal">
        {t('modals.saveKey.disclaimer')}
      </h3>
      <div className="flex justify-between py-2">
        <div>
          <h2 className="text-jet dark:text-bright-gray text-base font-semibold">
            API Key
          </h2>
          <span className="text-jet dark:text-bright-gray text-sm leading-7 font-normal">
            {apiKey}
          </span>
        </div>
        <button
          className="border-violets-are-blue text-violets-are-blue hover:bg-violets-are-blue my-1 h-10 w-20 rounded-full border border-solid p-2 text-sm hover:text-white"
          onClick={handleCopyKey}
        >
          {isCopied ? t('modals.saveKey.copied') : t('modals.saveKey.copy')}
        </button>
      </div>
      <button
        onClick={close}
        className="bg-philippine-yellow rounded-full px-4 py-3 font-medium text-black hover:bg-[#E6B91A]"
      >
        {t('modals.saveKey.confirm')}
      </button>
    </WrapperModal>
  );
}

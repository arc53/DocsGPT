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
      <h1 className="my-0 text-xl font-medium text-jet dark:text-bright-gray">
        {t('modals.saveKey.note')}
      </h1>
      <h3 className="text-sm font-normal text-outer-space dark:text-silver">
        {t('modals.saveKey.disclaimer')}
      </h3>
      <div className="flex justify-between py-2">
        <div>
          <h2 className="text-base font-semibold text-jet dark:text-bright-gray">
            API Key
          </h2>
          <span className="text-sm font-normal leading-7 text-jet dark:text-bright-gray">
            {apiKey}
          </span>
        </div>
        <button
          className="my-1 h-10 w-20 rounded-full border border-solid border-violets-are-blue p-2 text-sm text-violets-are-blue hover:bg-violets-are-blue hover:text-white"
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
    </WrapperModal>
  );
}

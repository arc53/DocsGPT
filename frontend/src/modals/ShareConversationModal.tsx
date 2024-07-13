import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import Spinner from '../assets/spinner.svg';
import Exit from '../assets/exit.svg';
const apiHost = import.meta.env.VITE_API_HOST || 'https://docsapi.arc53.com';

export const ShareConversationModal = ({
  close,
  conversationId,
}: {
  close: () => void;
  conversationId: string;
}) => {
  const [identifier, setIdentifier] = useState<null | string>(null);
  const [isCopied, setIsCopied] = useState(false);
  type StatusType = 'loading' | 'idle' | 'fetched' | 'failed';
  const [status, setStatus] = useState<StatusType>('idle');
  const { t } = useTranslation();
  const domain = window.location.origin;
  const handleCopyKey = (url: string) => {
    navigator.clipboard.writeText(url);
    setIsCopied(true);
  };
  const shareCoversationPublicly: (isPromptable: boolean) => void = (
    isPromptable = false,
  ) => {
    setStatus('loading');
    fetch(`${apiHost}/api/share?isPromptable=${isPromptable}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ conversation_id: conversationId }),
    })
      .then((res) => {
        console.log(res.status);
        return res.json();
      })
      .then((data) => {
        if (data.success && data.identifier) {
          setIdentifier(data.identifier);
          setStatus('fetched');
        } else setStatus('failed');
      })
      .catch((err) => setStatus('failed'));
  };
  return (
    <div className="fixed top-0 left-0 z-30 flex h-screen w-screen items-center justify-center bg-gray-alpha bg-opacity-50 text-chinese-black dark:text-silver">
      <div className="relative w-11/12 rounded-2xl bg-white p-10 dark:bg-outer-space sm:w-[512px]">
        <button className="absolute top-3 right-4 m-2 w-3" onClick={close}>
          <img className="filter dark:invert" src={Exit} />
        </button>
        <div className="flex flex-col gap-2">
          <h2 className="text-xl font-medium">{t('modals.shareConv.label')}</h2>
          <p className="text-sm">{t('modals.shareConv.note')}</p>
          <div className="flex items-baseline justify-between gap-2">
            <span className="no-scrollbar w-full overflow-x-auto whitespace-nowrap rounded-full border-2 p-3 shadow-inner">{`${domain}/share/${
              identifier ?? '....'
            }`}</span>
            {status === 'fetched' ? (
              <button
                className="my-1 h-10 w-36 rounded-full border border-solid border-purple-30 p-2 text-sm text-purple-30 hover:bg-purple-30 hover:text-white"
                onClick={() => handleCopyKey(`${domain}/share/${identifier}`)}
              >
                {isCopied
                  ? t('modals.saveKey.copied')
                  : t('modals.saveKey.copy')}
              </button>
            ) : (
              <button
                className="my-1 flex h-10 w-36 items-center justify-evenly rounded-full  border border-solid border-purple-30 p-2 text-center text-sm font-bold text-purple-30 hover:bg-purple-30 hover:text-white"
                onClick={() => {
                  shareCoversationPublicly(false);
                }}
              >
                {t('modals.shareConv.create')}
                {status === 'loading' && (
                  <img
                    src={Spinner}
                    className="inline animate-spin cursor-pointer bg-transparent filter dark:invert"
                  ></img>
                )}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

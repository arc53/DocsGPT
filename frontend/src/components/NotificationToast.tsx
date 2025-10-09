import { useEffect } from 'react';
import { toast } from 'sonner';

export function NotificationToast() {
  useEffect(() => {
    const message = import.meta.env.VITE_NOTIFICATION_TEXT;
    const link = import.meta.env.VITE_NOTIFICATION_LINK;

    console.log('Omar Emad , ', message, link);
    if (!message) return;

    const lastSeenNotification = localStorage.getItem('lastseennotification');
    if (lastSeenNotification === `${message}/${link}`) return;
    localStorage.setItem('lastseennotification', `${message}/${link}`);

    toast.custom(
      (t) => (
        <div
          onClick={() => toast.dismiss(t)}
          className="flex cursor-pointer items-center justify-between gap-3 rounded-lg bg-[linear-gradient(90deg,rgba(57,0,134,0)_16.83%,#6222B7_53.02%,rgba(57,0,134,0)_87.5%),linear-gradient(90deg,#390086_0%,#6222B7_100%)] px-5 py-4 text-sm text-white transition select-none hover:opacity-90"
        >
          {link ? (
            <a
              href={link}
              target="_blank"
              rel="noopener noreferrer"
              onClick={(e) => e.stopPropagation()}
              className="underline hover:no-underline"
            >
              {message}
            </a>
          ) : (
            <span>{message}</span>
          )}

          <button
            onClick={(e) => {
              e.stopPropagation();
              toast.dismiss(t);
            }}
            className="text-lg leading-none font-bold text-white/70 hover:text-white"
          >
            ×
          </button>
        </div>
      ),
      { duration: 10000, position: 'bottom-right' }, // 10 seconds , measured in ms
    );
  }, []);

  return null; // this component doesn’t render anything itself
}

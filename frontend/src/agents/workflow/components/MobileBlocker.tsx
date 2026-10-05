import { Monitor } from 'lucide-react';
import { useTranslation } from 'react-i18next';

export default function MobileBlocker() {
  const { t } = useTranslation();
  return (
    <div className="bg-background flex min-h-dvh flex-col items-center justify-center px-6 text-center lg:hidden">
      <div className="bg-secondary mb-6 flex size-20 items-center justify-center rounded-2xl">
        <Monitor className="text-primary size-10" />
      </div>
      <h2 className="text-foreground mb-2 text-xl leading-tight font-semibold">
        {t('agents.workflow.mobileBlocker.title')}
      </h2>
      <p className="text-muted-foreground max-w-sm text-sm leading-relaxed">
        {t('agents.workflow.mobileBlocker.body')}
      </p>
    </div>
  );
}

import { useTranslation } from 'react-i18next';

import { Alert, AlertAction, AlertDescription } from '../components/ui/alert';
import { useWorkspace } from '../workspace/useWorkspace';
import { PERSONAL_WORKSPACE } from '../workspace/requestWorkspace';

/**
 * In place of a page whose items only exist in Personal (Connectors, Custom
 * models), shown in a team workspace: an info Alert that says so, with
 * "Switch to Personal".
 *
 * Args:
 *   message: What is personal and where to manage it.
 */
export default function PersonalOnlyNotice({ message }: { message: string }) {
  const { t } = useTranslation();
  const { switchTo } = useWorkspace();
  return (
    <Alert variant="info" data-testid="personal-only-notice">
      <AlertDescription>
        <div className="flex flex-col items-start gap-2">
          <span>{message}</span>
          <AlertAction onClick={() => switchTo(PERSONAL_WORKSPACE)}>
            {t('settings.connectors.personalOnly.switch')}
          </AlertAction>
        </div>
      </AlertDescription>
    </Alert>
  );
}

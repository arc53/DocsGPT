import {
  Database,
  KeyRound,
  Link2,
  ScrollText,
  UsersRound,
  Webhook,
  Wrench,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { Card } from '@/components/ui/card';
import { ListRow, ListRows } from '@/components/ui/list-row';
import { Modal, ModalActions } from '@/components/ui/modal';
import { SectionHeader } from '@/components/ui/section-header';

import { intlLocale } from '../../utils/dateTimeUtils';
import type { SponsorConfirmation, SponsorResource } from '../sponsorConsent';

type SponsorConfirmModalProps = {
  /** The pending request from a refused save; null keeps the modal closed. */
  confirmation: SponsorConfirmation | null;
  /** Retry the save with these `confirm_sponsor` keys. */
  onConfirm: (keys: string[]) => void;
  onCancel: () => void;
  pending?: boolean;
};

const TYPE_ICONS: Record<SponsorResource['type'], typeof Wrench> = {
  tool: Wrench,
  source: Database,
  prompt: ScrollText,
};

function IconSquare({ icon: Icon }: { icon: typeof Wrench }) {
  return (
    <span className="bg-muted text-muted-foreground flex size-8 shrink-0 items-center justify-center rounded-md">
      <Icon className="size-4" />
    </span>
  );
}

/**
 * Asks an editor before a save makes tools, sources or prompts the agent's
 * owner can't use run with the editor's access, and says who will reach them
 * through the agent. Confirming retries the save with `confirm_sponsor`.
 * In `takeOver` mode the items are already attached (stopped), so the copy
 * says they will run with the editor's access rather than be added.
 */
export default function SponsorConfirmModal({
  confirmation,
  onConfirm,
  onCancel,
  pending = false,
}: SponsorConfirmModalProps) {
  const { t, i18n } = useTranslation();
  if (!confirmation) return null;

  const { resources, audience } = confirmation;
  const takeOver = confirmation.mode === 'takeOver';
  const count = { count: resources.length };
  const listFormat = new Intl.ListFormat(intlLocale(i18n.language), {
    type: 'conjunction',
  });
  const audienceRows: { key: string; icon: typeof Wrench; text: string }[] = [];
  if (audience.teams.length > 0) {
    audienceRows.push({
      key: 'teams',
      icon: UsersRound,
      text: t('agents.form.sponsorConfirm.audienceTeams', {
        teams: listFormat.format(audience.teams),
        interpolation: { escapeValue: false },
      }),
    });
  }
  if (audience.api_key) {
    audienceRows.push({
      key: 'api',
      icon: KeyRound,
      text: t('agents.form.sponsorConfirm.audienceApiKey'),
    });
  }
  if (audience.public_link) {
    audienceRows.push({
      key: 'link',
      icon: Link2,
      text: t('agents.form.sponsorConfirm.audiencePublicLink'),
    });
  }
  if (audience.webhook) {
    audienceRows.push({
      key: 'webhook',
      icon: Webhook,
      text: t('agents.form.sponsorConfirm.audienceWebhook'),
    });
  }
  if (audienceRows.length === 0) {
    audienceRows.push({
      key: 'editors',
      icon: UsersRound,
      text: t('agents.form.sponsorConfirm.audienceEditors'),
    });
  }

  return (
    <Modal
      mobileVariant="dialog"
      open
      onOpenChange={(open) => {
        if (!open) onCancel();
      }}
      isPerformingTask={pending}
      title={t('agents.form.sponsorConfirm.title')}
      description={t(
        takeOver
          ? 'agents.form.sponsorConfirm.takeOverDescription'
          : 'agents.form.sponsorConfirm.description',
        count,
      )}
      footer={
        <ModalActions
          cancelLabel={t('cancel')}
          onCancel={onCancel}
          submitLabel={t(
            takeOver
              ? 'agents.form.sponsorConfirm.takeOverConfirm'
              : 'agents.form.sponsorConfirm.confirm',
          )}
          onSubmit={() => onConfirm(resources.map((item) => item.key))}
          pending={pending}
        />
      }
    >
      <div className="flex flex-col gap-6">
        <Card variant="outline" padding="none" className="overflow-hidden">
          <ListRows>
            {resources.map((item) => (
              <ListRow
                key={item.key}
                leading={<IconSquare icon={TYPE_ICONS[item.type] ?? Wrench} />}
                title={item.name || t('agents.form.sponsors.unknownItem')}
                description={t(`agents.form.sponsorConfirm.types.${item.type}`)}
              />
            ))}
          </ListRows>
        </Card>
        <section className="flex flex-col gap-3">
          <SectionHeader
            as="h3"
            size="xs"
            title={t('agents.form.sponsorConfirm.audienceTitle', count)}
          />
          <ul className="flex flex-col gap-2">
            {audienceRows.map(({ key, icon: Icon, text }) => (
              <li
                key={key}
                className="text-foreground flex items-start gap-2 text-sm"
              >
                <Icon className="text-muted-foreground mt-0.5 size-4 shrink-0" />
                <span className="min-w-0">{text}</span>
              </li>
            ))}
          </ul>
          <p className="text-muted-foreground text-xs">
            {t('agents.form.sponsorConfirm.stopNote', count)}
          </p>
        </section>
      </div>
    </Modal>
  );
}

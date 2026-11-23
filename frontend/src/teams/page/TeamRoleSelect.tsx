import { useTranslation } from 'react-i18next';

import type {
  AssignableTeamRole,
  TeamRole,
} from '../../api/services/teamsService';
import { Badge } from '../../components/ui/badge';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../../components/ui/select';

/** The roles a member can be given, weakest first. */
export const ASSIGNABLE_TEAM_ROLES: ReadonlyArray<AssignableTeamRole> = [
  'viewer',
  'editor',
  'admin',
];

/** A role as a word, in the switcher's words. */
export function TeamRoleBadge({ role }: { role: TeamRole }) {
  const { t } = useTranslation();
  return (
    <Badge
      variant={role === 'owner' || role === 'admin' ? 'default' : 'neutral'}
      className="shrink-0"
    >
      {t(`workspace.common.roles.${role}`)}
    </Badge>
  );
}

type TeamRoleSelectProps = {
  value: TeamRole;
  onChange: (role: AssignableTeamRole) => void;
  /** `sm` on a member row, `field` in a form. */
  size?: 'sm' | 'field';
  disabled?: boolean;
  className?: string;
  'aria-label'?: string;
};

/**
 * A team role picker: Viewer, Editor or Admin. The owner is shown as a word,
 * not a select, because only a transfer changes who owns the team.
 */
export default function TeamRoleSelect({
  value,
  onChange,
  size = 'sm',
  disabled,
  className,
  'aria-label': ariaLabel,
}: TeamRoleSelectProps) {
  const { t } = useTranslation();
  if (value === 'owner') return <TeamRoleBadge role="owner" />;
  return (
    <Select
      value={value}
      disabled={disabled}
      onValueChange={(next) => onChange(next as AssignableTeamRole)}
    >
      <SelectTrigger size={size} className={className} aria-label={ariaLabel}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {ASSIGNABLE_TEAM_ROLES.map((role) => (
          <SelectItem key={role} value={role}>
            {t(`workspace.common.roles.${role}`)}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

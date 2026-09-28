import { ArrowRight } from 'lucide-react';
import { useTranslation } from 'react-i18next';

// Variable names are the user's own text: React escapes on render.
const NO_ESCAPE = { interpolation: { escapeValue: false } } as const;

/**
 * A node's output variable on the canvas: an arrow, then the name in mono,
 * because it is what the next node reads.
 *
 * Args:
 *   variable: The output variable's name.
 */
export default function OutputVariableLine({ variable }: { variable: string }) {
  const { t } = useTranslation();
  return (
    <div
      className="text-muted-foreground flex min-w-0 items-center gap-1 text-xs"
      title={t('agents.workflow.nodes.output', { ...NO_ESCAPE, variable })}
    >
      <ArrowRight className="size-3 shrink-0" aria-hidden="true" />
      <span className="truncate font-mono">{variable}</span>
    </div>
  );
}

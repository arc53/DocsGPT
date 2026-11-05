import { MessageSquare } from 'lucide-react';

import { cleanStarters } from '../agents/starters';
import SuggestionRows, { suggestionIconClass } from './SuggestionRows';

/**
 * An agent's starters under its card on a new chat: the owner's questions,
 * drawn as the empty chat's suggestion rows, each sending itself.
 */
export default function AgentStarters({
  starters,
  onAsk,
  className,
}: {
  starters?: string[] | null;
  onAsk: (question: string) => void;
  className?: string;
}) {
  return (
    <SuggestionRows
      className={className}
      rows={cleanStarters(starters).map((text, index) => ({
        key: `starter-${index}`,
        icon: <MessageSquare className={suggestionIconClass} />,
        text,
        asks: true,
        onSelect: () => onAsk(text),
      }))}
    />
  );
}

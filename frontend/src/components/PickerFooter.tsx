import { ArrowRight } from 'lucide-react';
import { Link } from 'react-router-dom';

import { Button } from './ui/button';

type PickerFooterProps = {
  /** The settings page the link opens. */
  to: string;
  linkLabel: string;
  /** Fires when the link is followed so the caller can close its popover. */
  onNavigate?: () => void;
  /**
   * The shortcut on the right (Upload new, Add tool). Left out where the
   * host can't use it (the workflow agent node's Tools: the builder loads
   * its tool list once), so the row is the link alone.
   */
  actionLabel?: string;
  onAction?: () => void;
};

/**
 * Shared footer for the pickers (knowledge, tools, prompts): a link to the
 * item's settings page on the left and, when given, a "new" action on the
 * right.
 */
export default function PickerFooter({
  to,
  linkLabel,
  onNavigate,
  actionLabel,
  onAction,
}: PickerFooterProps) {
  return (
    // One row when it fits (link left, action right); on a narrow sheet or a
    // long locale the button wraps under the link.
    <div className="flex flex-wrap items-center justify-between gap-3">
      <Button variant="link" size="inline" asChild>
        <Link to={to} onClick={onNavigate}>
          {linkLabel}
          <ArrowRight aria-hidden="true" />
        </Link>
      </Button>
      {actionLabel && onAction ? (
        <Button
          type="button"
          variant="outline-primary"
          shape="pill"
          onClick={onAction}
        >
          {actionLabel}
        </Button>
      ) : null}
    </div>
  );
}

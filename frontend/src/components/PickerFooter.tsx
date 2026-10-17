import { ArrowRight } from 'lucide-react';
import { Link } from 'react-router-dom';

import { Button } from './ui/button';

type PickerFooterProps = {
  /** The settings page the link opens. */
  to: string;
  linkLabel: string;
  /** Fires when the link is followed so the caller can close its popover. */
  onNavigate?: () => void;
  actionLabel: string;
  onAction: () => void;
};

/**
 * Shared footer for the composer's pickers (knowledge, tools): a link to the
 * item's settings page on the left and a "new" action on the right.
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
      <Button
        type="button"
        variant="outline-primary"
        shape="pill"
        onClick={onAction}
      >
        {actionLabel}
      </Button>
    </div>
  );
}

import type { ReactNode } from 'react';

import {
  Card,
  CardAction,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from '../components/ui/card';

type ConnectorTileProps = {
  /** A 24px logo or tool icon (`size-6 shrink-0`). */
  icon: ReactNode;
  title: string;
  /**
   * The title's level in the page outline. Only for a tile that is not a
   * button: a button flattens the headings inside it.
   */
  titleAs?: 'div' | 'h2' | 'h3';
  description?: ReactNode;
  /** The badge row: the state first, then categories (role, capabilities). */
  badges?: ReactNode;
  /** The meta row: an account line, a Connect cue, a switch. */
  footer?: ReactNode;
  /** An `ActionMenu` in the header's corner; never on a button tile. */
  menu?: ReactNode;
  /** `filled` for a tile on a page, `outline` for a choice in a picker. */
  variant?: 'filled' | 'outline';
  /** Makes the whole tile one button. */
  onClick?: () => void;
  disabled?: boolean;
  testId?: string;
};

/**
 * One tile for a connector or a tool, wherever it is listed: the Connectors
 * catalog, the Tools page and the Add a tool picker. A header row with the
 * icon and the name (and a menu on a tile that is not a button), a two-line
 * description, the badge row and a footer for meta. Rows even out through
 * the grid, so the tile has no fixed height.
 */
export default function ConnectorTile({
  icon,
  title,
  titleAs = 'div',
  description,
  badges,
  footer,
  menu,
  variant = 'filled',
  onClick,
  disabled = false,
  testId,
}: ConnectorTileProps) {
  const body = (
    <>
      <CardHeader className="w-full">
        <span className="flex min-w-0 items-center gap-3">
          {icon}
          <CardTitle
            as={onClick ? 'div' : titleAs}
            className="min-w-0 truncate"
            title={title}
          >
            {title}
          </CardTitle>
        </span>
        {menu && !onClick ? (
          <CardAction className="-my-0.5 -mr-2">{menu}</CardAction>
        ) : null}
      </CardHeader>
      {description ? (
        <CardDescription size="xs" className="line-clamp-2 wrap-break-word">
          {description}
        </CardDescription>
      ) : null}
      {badges ? (
        <div
          data-slot="tile-badges"
          className="flex flex-wrap gap-1 empty:hidden"
        >
          {badges}
        </div>
      ) : null}
      {footer ? (
        <CardFooter className="w-full empty:hidden">{footer}</CardFooter>
      ) : null}
    </>
  );

  if (!onClick) {
    return (
      <Card
        variant={variant}
        padding="lg"
        className="h-full"
        data-testid={testId}
      >
        {body}
      </Card>
    );
  }
  return (
    <Card
      asChild
      variant={variant}
      padding="lg"
      interactive={!disabled}
      className="h-full w-full"
    >
      <button
        type="button"
        disabled={disabled}
        onClick={onClick}
        data-testid={testId}
      >
        {body}
      </button>
    </Card>
  );
}

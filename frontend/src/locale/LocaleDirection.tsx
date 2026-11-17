import type { ReactNode } from 'react';
import { Direction } from 'radix-ui';
import { useTranslation } from 'react-i18next';

/** Keep portalled Radix menus and their keyboard navigation in the UI direction. */
export default function LocaleDirection({ children }: { children: ReactNode }) {
  const { i18n } = useTranslation();
  return <Direction.Provider dir={i18n.dir()}>{children}</Direction.Provider>;
}

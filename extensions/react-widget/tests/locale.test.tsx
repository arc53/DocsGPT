import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';

import {
  buildMessages,
  interpolate,
  localeDirection,
  resolveLocale,
  SUPPORTED_LOCALES,
} from '../src/locale';
import { en } from '../src/locale/en';
import { fa } from '../src/locale/fa';
import { DocsGPTWidget } from '../src/components/DocsGPTWidget';

describe('Persian widget locale', () => {
  it('covers every English message and preserves interpolation', () => {
    expect(Object.keys(fa).sort()).toEqual(Object.keys(en).sort());
    for (const key of Object.keys(en) as (keyof typeof en)[]) {
      expect(fa[key].match(/\{\w+\}/g) ?? []).toEqual(
        en[key].match(/\{\w+\}/g) ?? [],
      );
    }
    expect(interpolate(fa.removeFile, { name: 'report-123.pdf' })).toBe(
      'حذف report-123.pdf',
    );
  });

  it('resolves explicit, regional, browser, and unsupported languages', () => {
    expect(SUPPORTED_LOCALES).toContain('fa');
    expect(resolveLocale('fa', ['en'])).toBe('fa');
    expect(resolveLocale('fa-IR')).toBe('fa');
    expect(resolveLocale('auto', ['xx', 'fa-AF'])).toBe('fa');
    expect(resolveLocale('xx', ['fa'])).toBe('en');
    expect(buildMessages('en').sendMessage).toBe(en.sendMessage);
    expect(localeDirection('fa')).toBe('rtl');
    expect(localeDirection('en')).toBe('ltr');
  });

  it('scopes RTL to the widget without altering the host document', () => {
    document.documentElement.dir = 'ltr';
    const markup = renderToStaticMarkup(
      <DocsGPTWidget
        locale="fa-IR"
        persistConversations={false}
        suggestedQuestions={[]}
      />,
    );
    expect(markup).toContain('lang="fa"');
    expect(markup).toContain('dir="rtl"');
    expect(markup).toContain(fa.launcherButton);
    expect(document.documentElement.dir).toBe('ltr');
  });

  it('keeps English LTR even when the embedding page is RTL', () => {
    document.documentElement.dir = 'rtl';
    const markup = renderToStaticMarkup(
      <DocsGPTWidget
        locale="en"
        persistConversations={false}
        suggestedQuestions={[]}
      />,
    );
    expect(markup).toContain('lang="en"');
    expect(markup).toContain('dir="ltr"');
    expect(markup).toContain(en.launcherButton);
    expect(document.documentElement.dir).toBe('rtl');
  });
});

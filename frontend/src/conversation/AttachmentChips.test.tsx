import i18n from 'i18next';
import { renderToStaticMarkup } from 'react-dom/server';
import { I18nextProvider, initReactI18next } from 'react-i18next';
import { beforeAll, describe, expect, it } from 'vitest';

import en from '../locale/en.json';
import AttachmentChips from './AttachmentChips';
import type { AttachmentPlanEntry } from './conversationModels';

const testI18n = i18n.createInstance();

beforeAll(async () => {
  await testI18n.use(initReactI18next).init({
    lng: 'en',
    fallbackLng: 'en',
    resources: { en: { translation: en } },
  });
});

const render = (
  files: { id: string; fileName: string }[],
  plan?: AttachmentPlanEntry[],
) =>
  renderToStaticMarkup(
    <I18nextProvider i18n={testI18n}>
      <AttachmentChips files={files} plan={plan} />
    </I18nextProvider>,
  );

const files = [
  { id: 'a', fileName: 'a.pdf' },
  { id: 'b', fileName: 'b.pdf' },
  { id: 'c', fileName: 'c.pdf' },
];

describe('AttachmentChips', () => {
  it('renders plain chips when there is no plan', () => {
    const html = render(files);
    expect(html).toContain('a.pdf');
    expect(html).not.toContain('data-plan-status');
    expect(html).not.toContain('read in full');
  });

  it('marks each chip with where the file went', () => {
    const html = render(files, [
      { ref: 'F1', id: 'a', filename: 'a.pdf', status: 'inline' },
      { ref: 'F2', id: 'b', filename: 'b.pdf', status: 'partial' },
      { ref: 'F3', id: 'c', filename: 'c.pdf', status: 'tool' },
    ]);
    expect(html).toContain('data-plan-status="inline"');
    expect(html).toContain('In context');
    expect(html).toContain('Partly in context');
    expect(html).toContain('Searchable');
    expect(html).toContain('1 of 3 files read in full · 2 searchable');
  });

  it('says nothing extra when every file was read in full', () => {
    const html = render(files.slice(0, 1), [
      { ref: 'F1', id: 'a', filename: 'a.pdf', status: 'inline' },
    ]);
    expect(html).toContain('In context');
    expect(html).not.toContain('read in full');
  });

  it('reports files that could not be included', () => {
    const html = render(files.slice(0, 2), [
      { ref: 'F1', id: 'a', filename: 'a.pdf', status: 'inline' },
      { ref: 'F2', id: 'b', filename: 'b.pdf', status: 'omitted' },
    ]);
    expect(html).toContain('Not included');
    expect(html).toContain('1 of 2 files read in full · 1 not included');
  });
});

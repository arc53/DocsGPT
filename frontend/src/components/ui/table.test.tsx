import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from './table';

function render(element: React.ReactElement): HTMLElement {
  const host = document.createElement('div');
  host.innerHTML = renderToStaticMarkup(element);
  return host;
}

describe('Table parts', () => {
  it('pass native attributes through to the element', () => {
    const host = render(
      <Table aria-label="Audit feed" data-testid="table">
        <TableHead data-testid="head">
          <TableRow data-testid="head-row">
            <TableHeader scope="col" width="120px">
              When
            </TableHeader>
          </TableRow>
        </TableHead>
        <TableBody data-testid="body">
          <TableRow aria-selected="true">
            <TableCell headers="when" align="right" colSpan={2}>
              Today
            </TableCell>
          </TableRow>
        </TableBody>
      </Table>,
    );
    const table = host.querySelector('table')!;
    expect(table.getAttribute('aria-label')).toBe('Audit feed');
    expect(table.dataset.slot).toBe('table');
    expect(host.querySelector('thead')!.dataset.testid).toBe('head');
    expect(host.querySelector('tbody')!.dataset.testid).toBe('body');
    const th = host.querySelector('th')!;
    expect(th.getAttribute('scope')).toBe('col');
    expect(th.getAttribute('style')).toContain('--cell-width:120px');
    expect(host.querySelector('tbody tr')!.getAttribute('aria-selected')).toBe(
      'true',
    );
    const td = host.querySelector('td')!;
    expect(td.getAttribute('headers')).toBe('when');
    expect(td.getAttribute('colspan')).toBe('2');
    expect(td.className).toContain('text-right');
  });

  it('draws a dense foreground header row', () => {
    const th = render(
      <table>
        <thead>
          <tr>
            <TableHeader>When</TableHeader>
          </tr>
        </thead>
      </table>,
    ).querySelector('th')!;
    const classes = th.className.split(' ');
    expect(classes).toEqual(
      expect.arrayContaining(['py-1', 'font-normal', 'text-foreground']),
    );
    expect(classes).not.toContain('py-3');
    expect(classes).not.toContain('text-muted-foreground');
  });

  // The row whose detail is open beside the table (the graph's Entities):
  // the brand tint of an open navigator item, so it never reads as hover.
  it('marks the open row with the secondary tint and aria-current', () => {
    const host = render(
      <table>
        <tbody>
          <TableRow data-testid="open" selected onClick={vi.fn()} />
          <TableRow data-testid="other" onClick={vi.fn()} />
        </tbody>
      </table>,
    );
    const open = host.querySelector<HTMLElement>('[data-testid="open"]')!;
    expect(open.dataset.selected).toBe('');
    expect(open.getAttribute('aria-current')).toBe('true');
    expect(open.className).toContain('bg-secondary');
    expect(open.className).toContain('hover:bg-secondary');
    const other = host.querySelector<HTMLElement>('[data-testid="other"]')!;
    expect(other.dataset.selected).toBeUndefined();
    expect(other.className).not.toContain('bg-secondary');
  });

  it('hovers only rows that have an onClick', () => {
    const host = render(
      <table>
        <tbody>
          <TableRow data-testid="plain" />
          <TableRow data-testid="clickable" onClick={() => undefined} />
        </tbody>
      </table>,
    );
    const plain = host.querySelector('[data-testid="plain"]')!.className;
    const clickable = host.querySelector(
      '[data-testid="clickable"]',
    )!.className;
    expect(plain).not.toContain('hover:');
    expect(plain).not.toContain('cursor-pointer');
    expect(clickable).toContain('hover:bg-accent');
    expect(clickable).toContain('cursor-pointer');
  });

  it('makes a clickable row focusable and opens it with Enter or Space', async () => {
    Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
    const onClick = vi.fn();
    const host = document.createElement('div');
    document.body.appendChild(host);
    const root = createRoot(host);
    await act(async () =>
      root.render(
        <table>
          <tbody>
            <TableRow data-testid="plain" />
            <TableRow data-testid="clickable" onClick={onClick}>
              <td>
                <button type="button">Inner</button>
              </td>
            </TableRow>
          </tbody>
        </table>,
      ),
    );
    const plain = host.querySelector('[data-testid="plain"]')!;
    const row = host.querySelector<HTMLElement>('[data-testid="clickable"]')!;
    expect(plain.hasAttribute('tabindex')).toBe(false);
    expect(row.getAttribute('tabindex')).toBe('0');
    expect(row.className).toContain('focus-visible:ring-3');

    const key = (target: Element, k: string) =>
      target.dispatchEvent(
        new KeyboardEvent('keydown', { key: k, bubbles: true }),
      );
    await act(async () => key(row, 'Enter'));
    await act(async () => key(row, ' '));
    expect(onClick).toHaveBeenCalledTimes(2);
    // A key on a control inside the row belongs to that control.
    await act(async () => key(row.querySelector('button')!, 'Enter'));
    expect(onClick).toHaveBeenCalledTimes(2);

    await act(async () => root.unmount());
    host.remove();
  });

  it('keeps the default minimum width on the table', () => {
    const table = render(<Table>{null}</Table>).querySelector('table')!;
    expect(table.className.split(' ')).toContain('min-w-[600px]');
  });
});

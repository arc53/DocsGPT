import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

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

  it('keeps the default minimum width on the table', () => {
    const table = render(<Table>{null}</Table>).querySelector('table')!;
    expect(table.className.split(' ')).toContain('min-w-[600px]');
  });
});

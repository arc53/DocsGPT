import { Copy, Pencil } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { IconButton } from '@/components/ui/icon-button';
import {
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Example, Section } from '../shared';

const TABLE_ROWS = [
  { name: 'Contracts & Policy Assistant', status: 'success', runs: 128 },
  { name: 'Customer Renewal Desk', status: 'info', runs: 42 },
  { name: 'Vendor Due Diligence', status: 'warning', runs: 9 },
  { name: 'Legacy importer', status: 'destructive', runs: 0 },
] as const;

export default function TableSection() {
  return (
    <Section
      id="tables"
      title="Tables"
      intro="Cells accept alignment and typography classes plus text-muted-foreground; everything else is layout."
    >
      <Example
        title="Table with status badges"
        code='<TableCell align="right" className="tabular-nums">'
      >
        <TableContainer>
          <Table>
            <TableHead>
              <TableRow>
                <TableHeader>Agent</TableHeader>
                <TableHeader>Status</TableHeader>
                <TableHeader align="right">Runs</TableHeader>
                <TableHeader align="right">Actions</TableHeader>
              </TableRow>
            </TableHead>
            <TableBody>
              {TABLE_ROWS.map((row) => (
                <TableRow key={row.name}>
                  <TableCell className="font-medium">{row.name}</TableCell>
                  <TableCell>
                    <Badge variant={row.status}>{row.status}</Badge>
                  </TableCell>
                  <TableCell align="right" className="tabular-nums">
                    {row.runs}
                  </TableCell>
                  <TableCell align="right">
                    <IconButton
                      size="icon-sm"
                      variant="ghost-muted"
                      label="Copy"
                      icon={Copy}
                    />
                    <IconButton
                      size="icon-sm"
                      variant="ghost-muted"
                      label="Edit"
                      icon={Pencil}
                    />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      </Example>
      <Example
        title="Clickable rows, one open beside the table"
        code="<TableRow selected onClick={…}>"
      >
        <TableContainer>
          <Table>
            <TableHead>
              <TableRow>
                <TableHeader>Entity</TableHeader>
                <TableHeader align="right">Connections</TableHeader>
              </TableRow>
            </TableHead>
            <TableBody>
              {TABLE_ROWS.map((row, index) => (
                <TableRow
                  key={row.name}
                  selected={index === 1}
                  onClick={() => undefined}
                >
                  <TableCell className="font-medium">{row.name}</TableCell>
                  <TableCell align="right" className="tabular-nums">
                    {row.runs}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      </Example>
    </Section>
  );
}

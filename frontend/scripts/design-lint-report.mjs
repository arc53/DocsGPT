#!/usr/bin/env node
/**
 * Summarise @shadcn/lint warnings from ESLint JSON output.
 *
 *   npm run lint:design              rules × counts, then the 25 worst files
 *   npm run lint:design -- --rule no-raw-colors   files for one rule
 *   npm run lint:design -- --file src/settings/Tools.tsx   every message in a file
 *
 * Reads ESLint's JSON from stdin; the npm script pipes it in.
 */
import { readFileSync } from 'node:fs';

const args = process.argv.slice(2);
const opt = (name) => {
  const i = args.indexOf(name);
  return i === -1 ? undefined : args[i + 1];
};
const onlyRule = opt('--rule');
const onlyFile = opt('--file');

const input = readFileSync(0, 'utf8');
const start = input.indexOf('[');
const results = JSON.parse(input.slice(start));

const rows = [];
for (const file of results) {
  const rel = file.filePath.replace(`${process.cwd()}/`, '');
  for (const m of file.messages) {
    if (!m.ruleId?.startsWith('shadcn/')) continue;
    rows.push({
      file: rel,
      rule: m.ruleId.slice(7),
      line: m.line,
      msg: m.message,
    });
  }
}

const count = (key) => {
  const c = new Map();
  for (const r of rows) c.set(r[key], (c.get(r[key]) ?? 0) + 1);
  return [...c.entries()].sort((a, b) => b[1] - a[1]);
};
const pad = (s, n) => String(s).padStart(n);

if (onlyFile) {
  const mine = rows.filter(
    (r) => r.file === onlyFile || r.file.endsWith(onlyFile),
  );
  console.log(`${mine.length} design warnings in ${onlyFile}\n`);
  for (const r of mine.sort((a, b) => a.line - b.line)) {
    console.log(
      `${pad(r.line, 5)}  ${r.rule}\n       ${r.msg.split(' See frontend/DESIGN.md')[0]}\n`,
    );
  }
} else if (onlyRule) {
  const mine = rows.filter((r) => r.rule === onlyRule);
  console.log(`${mine.length} warnings for shadcn/${onlyRule}\n`);
  const byFile = new Map();
  for (const r of mine) byFile.set(r.file, (byFile.get(r.file) ?? 0) + 1);
  for (const [f, n] of [...byFile.entries()].sort((a, b) => b[1] - a[1]))
    console.log(`${pad(n, 5)}  ${f}`);
} else {
  console.log(
    `${rows.length} design warnings in ${new Set(rows.map((r) => r.file)).size} files\n`,
  );
  console.log('By rule:');
  for (const [rule, n] of count('rule')) console.log(`${pad(n, 5)}  ${rule}`);
  console.log('\nWorst files:');
  for (const [file, n] of count('file').slice(0, 25))
    console.log(`${pad(n, 5)}  ${file}`);
  console.log(
    '\nNext: npm run lint:design -- --file <path>   or   -- --rule <rule>',
  );
}

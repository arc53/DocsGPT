/**
 * Parse/build the Simple-mode condition expressions. The variable side accepts
 * dotted paths (`audit.high_risk_accounts`) because the engine's CEL evaluator
 * resolves them — Simple mode rejecting what the backend happily runs left
 * saved workflows blocked at Preview with "must specify a variable".
 */

export function parseSimpleCel(expression: string): {
  variable: string;
  operator: string;
  value: string;
} {
  const trimmedExpression = expression.trim();

  let match = trimmedExpression.match(
    /^([\w.]+)\.(contains|startsWith)\(["'](.*)["']\)$/,
  );
  if (match) return { variable: match[1], operator: match[2], value: match[3] };

  match = trimmedExpression.match(/^([\w.]+)\.(contains|startsWith)\((.*)\)$/);
  if (match) {
    const rawValue = match[3].trim();
    const unquotedValue = rawValue.replace(/^["'](.*)["']$/, '$1');
    return {
      variable: match[1],
      operator: match[2],
      value: unquotedValue,
    };
  }

  match = trimmedExpression.match(/^(contains|startsWith)\(["'](.*)["']\)$/);
  if (match) return { variable: '', operator: match[1], value: match[2] };

  match = trimmedExpression.match(/^(contains|startsWith)\((.*)\)$/);
  if (match) {
    const rawValue = match[2].trim();
    const unquotedValue = rawValue.replace(/^["'](.*)["']$/, '$1');
    return { variable: '', operator: match[1], value: unquotedValue };
  }

  match = trimmedExpression.match(
    /^([\w.]+)\s*(==|!=|>=|<=|>|<)\s*["'](.*)["']$/,
  );
  if (match) return { variable: match[1], operator: match[2], value: match[3] };

  match = trimmedExpression.match(/^(==|!=|>=|<=|>|<)\s*["'](.*)["']$/);
  if (match) return { variable: '', operator: match[1], value: match[2] };

  match = trimmedExpression.match(/^([\w.]+)\s*(==|!=|>=|<=|>|<)\s*(.*)$/);
  if (match) return { variable: match[1], operator: match[2], value: match[3] };

  match = trimmedExpression.match(/^(==|!=|>=|<=|>|<)\s*(.*)$/);
  if (match) return { variable: '', operator: match[1], value: match[2] };

  return { variable: '', operator: '==', value: '' };
}

export function buildSimpleCel(
  variable: string,
  operator: string,
  value: string,
): string {
  const trimmedValue = value.trim();
  const isNumeric = trimmedValue !== '' && !isNaN(Number(trimmedValue));
  const isBool = trimmedValue === 'true' || trimmedValue === 'false';
  const literalValue =
    isNumeric || isBool ? trimmedValue : JSON.stringify(value);
  const stringValue = JSON.stringify(value);
  if (operator === 'contains') {
    return variable
      ? `${variable}.contains(${stringValue})`
      : `contains(${stringValue})`;
  }
  if (operator === 'startsWith') {
    return variable
      ? `${variable}.startsWith(${stringValue})`
      : `startsWith(${stringValue})`;
  }
  if (!variable) return `${operator} ${literalValue}`;
  return `${variable} ${operator} ${literalValue}`;
}

type ToolLabelSource = {
  customName?: string | null;
  displayName?: string | null;
  display_name?: string | null;
  name?: string | null;
};

const isNonEmptyString = (value: unknown): value is string =>
  typeof value === 'string' && value.trim().length > 0;

export function getToolDisplayName(tool: ToolLabelSource): string {
  if (isNonEmptyString(tool.customName)) return tool.customName.trim();
  if (isNonEmptyString(tool.displayName)) return tool.displayName.trim();
  if (isNonEmptyString(tool.display_name)) return tool.display_name.trim();
  if (isNonEmptyString(tool.name)) return tool.name.trim();
  return '';
}

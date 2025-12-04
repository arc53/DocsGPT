export type DropdownOptionBase = {
  id?: string;
  type?: string;
};

export type StringOption = string;
export type NameIdOption = { name: string; id: string } & DropdownOptionBase;
export type LabelValueOption = {
  label: string;
  value: string;
} & DropdownOptionBase;
export type ValueDescriptionOption = {
  value: number;
  description: string;
} & DropdownOptionBase;

export type DropdownOption =
  | StringOption
  | NameIdOption
  | LabelValueOption
  | ValueDescriptionOption;

export type DropdownSelectedValue = DropdownOption | null;

export type OnSelectHandler<T extends DropdownOption = DropdownOption> = (
  value: T,
) => void;

export interface DropdownProps<T extends DropdownOption = DropdownOption> {
  options: T[];
  selectedValue: DropdownSelectedValue;
  onSelect: OnSelectHandler<T>;
  size?: string;
  rounded?: 'xl' | '3xl';
  buttonClassName?: string;
  optionsClassName?: string;
  border?: 'border' | 'border-2';
  showEdit?: boolean;
  onEdit?: (value: NameIdOption) => void;
  showDelete?: boolean | ((option: T) => boolean);
  onDelete?: (id: string) => void;
  placeholder?: string;
  placeholderClassName?: string;
  contentSize?: string;
}

export type ConfigFieldSpec = {
  type: 'string' | 'number' | 'boolean';
  label: string;
  description: string;
  required?: boolean;
  secret?: boolean;
  order?: number;
  enum?: string[];
  default?: string | number | boolean;
  depends_on?: { [key: string]: string };
};

export type ConfigRequirements = {
  [key: string]: ConfigFieldSpec;
};

export type AvailableToolType = {
  name: string;
  displayName: string;
  description: string;
  configRequirements: ConfigRequirements;
  actions: {
    name: string;
    description: string;
    parameters: object;
  }[];
};

export type WrapperModalPropsType = {
  children?: React.ReactNode;
  isPerformingTask?: boolean;
  close: () => void;
  className?: string;
};

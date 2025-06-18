export type AvailableToolType = {
  name: string;
  displayName: string;
  description: string;
  configRequirements: object;
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

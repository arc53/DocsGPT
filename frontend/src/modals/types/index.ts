export type AvailableTool = {
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

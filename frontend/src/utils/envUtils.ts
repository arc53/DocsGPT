type Env = Record<string, string>;

export const getEnv = (key: string): string | undefined => {
  return (window as { _env_?: Env })?._env_?.[key] ?? import.meta.env?.[key];
};

export type ActiveState = 'ACTIVE' | 'INACTIVE';

export type User = {
  avatar: string;
};

export type Doc = {
  name: string;
  language: string;
  version: string;
  description: string;
  fullName: string;
  dat: string;
  docLink: string;
  model: string;
};

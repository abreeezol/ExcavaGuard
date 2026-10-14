export const DEFAULT_PROJECT_ID = "11111111-1111-4111-8111-111111111111";

export type LocalAccess = {
  owner_id: "local-operator";
  project_id: string;
};

export type AccessStatus = {
  mode: "local" | "password";
  authenticated: boolean;
  project_id: string;
};

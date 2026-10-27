export const DEFAULT_PROJECT_ID = "11111111-1111-4111-8111-111111111111";

export type LocalAccess = {
  owner_id: string;
  project_id: string;
  role?: ProjectRole;
};

export type ProjectRole = "admin" | "reviewer" | "engineer" | "viewer";
export type AuthorizedProject = { id: string; name: string; role: ProjectRole };

export type AccessStatus = {
  mode: "local" | "password" | "accounts";
  authenticated: boolean;
  project_id: string | null;
  user?: { id: string; name: string } | null;
  projects?: AuthorizedProject[];
  can_create_project?: boolean;
};

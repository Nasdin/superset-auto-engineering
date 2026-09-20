export type CheckItem = {
  id: string;
  title: string;
  detail: string;
  status: string;
  duration: string;
  kind: string;
  content: string;
};
export type Workflow = {
  id: string;
  issue: number;
  title: string;
  area: string;
  status: string;
  run: string;
  minutes: number;
};
export type Data = {
  mode: string;
  repository: string;
  candidate: {
    id: string;
    sha: string;
    branch: string;
    validator: string;
    status: string;
  };
  checks: CheckItem[];
  workflows: Workflow[];
  events: {
    id: number;
    kind: string;
    created: string;
    payload: { title?: string; decision?: string; note?: string };
  }[];
};

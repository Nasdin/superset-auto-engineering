export type Artifact = { kind: string; name: string; url: string };
export type Job = {
  id: string;
  kind: string;
  state: string;
  session_url: string | null;
  candidate_sha: string | null;
  pr_number: number | null;
  error: string | null;
  acu: number;
  created: number;
  payload: { title?: string; issue_number?: number; source?: string };
  result?: {
    summary?: string;
    artifacts?: Artifact[];
    checks?: {
      name: string;
      passed: boolean;
      detail: string;
      command: string;
    }[];
  };
};
export type Overview = {
  repository: string;
  branch: string;
  enabled: boolean;
  connections: Record<string, boolean>;
  limits: {
    max_acu_per_session: number;
    max_sessions_total: number;
    scan_interval_seconds: number;
  };
  worker: { state?: string; at?: number };
  jobs: Job[];
  publications: { key: string; state: string; url?: string; error?: string }[];
  metrics: {
    sessions: number;
    acu: number;
    review_ready: number;
    attention: number;
  };
  memory: { summary: string; status: string }[];
};

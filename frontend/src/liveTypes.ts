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
  updated: number;
  started: number | null;
  parent_id: string | null;
  payload: {
    title?: string;
    work_type?: string;
    issue_number?: number;
    source?: string;
    members?: { job_id: string; pr_number: number; sha: string }[];
    implementation_jobs?: string[];
  };
  result?: {
    summary?: string;
    gate_failures?: string[];
    provenance?: string;
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

export type Artifact = {
  kind: string;
  name: string;
  url: string;
  public_url?: string;
};
export type Job = {
  id: string;
  kind: string;
  lane?: string;
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
    api_requests?: {
      name: string;
      method: string;
      url: string;
      curl: string;
      expected_status: number;
      actual_status: number;
      assertion: string;
      response_excerpt: string;
      passed: boolean;
      evidence_url: string;
    }[];
    test_results?: {
      command: string;
      passed: number;
      failed: number;
      skipped: number;
      report_url: string;
    };
    coverage?: {
      command: string;
      scope: string;
      lines_covered: number;
      lines_total: number;
      branches_covered: number;
      branches_total: number;
      report_url: string;
    };
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

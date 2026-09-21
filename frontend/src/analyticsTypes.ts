export type Cohort = {
  start: string;
  end: string;
  merged: number;
  sample_size: number;
  excluded_invalid: number;
  median_hours: number | null;
  p75_hours: number | null;
  covered: boolean;
};
export type PRRow = {
  number: number;
  title: string;
  url: string;
  author: string;
  labels: string[];
  created_at: string;
  merged_at: string;
  hours_to_merge: number | null;
  category: string;
  tracked: boolean;
};
export type Analytics = {
  data_revision: number;
  backfill: {
    state: "ready" | "loading" | "attention";
    pending_months: number;
    months: {
      month: string;
      state:
        "queued" | "running" | "ready" | "retry" | "blocked" | "dead_letter";
      covered_through: string | null;
      requested_through: string;
      next_retry: number;
    }[];
  };
  impact: Impact;
  repository: string;
  repositories: string[];
  workflow_repository: string;
  provenance: string;
  current: Cohort;
  baseline: Cohort;
  change_percent: number | null;
  trend: Cohort[];
  opened: number;
  closed_unmerged: number;
  observed_open: number;
  total_rows: number;
  rows: PRRow[];
  offset: number;
  stored_prs: number;
  categories: Record<string, number>;
  filters: { authors: string[]; labels: string[]; bases: string[] };
  sync: {
    state: string;
    coverage_from?: string;
    last_success?: string;
    pages?: number;
    error?: string | null;
  };
};

export type ImpactMeasure = {
  start: string;
  end: string;
  covered: boolean;
  merged_prs: number;
  merge_samples: number;
  commits_samples: number;
  rework_samples: number;
  code_samples: number;
  median_hours: number | null;
  total_hours: number | null;
  covered_total_hours: number | null;
  avg_commits: number | null;
  avg_rework: number | null;
  additions: number | null;
  deletions: number | null;
  avg_lines_changed: number | null;
};
export type Impact = {
  rollout_date: string;
  current: ImpactMeasure;
  baseline: ImpactMeasure;
  changes: Record<string, number | null>;
  categories: {
    segment: string;
    current: ImpactMeasure;
    baseline: ImpactMeasure;
    changes: Record<string, number | null>;
  }[];
  monthly: (ImpactMeasure & { month: string; segment: string })[];
  monthly_totals: (ImpactMeasure & { month: string })[];
  rollout: {
    before: ImpactMeasure;
    after: ImpactMeasure | null;
    days: number;
    changes: Record<string, number | null>;
  };
  estimate: {
    eligible_prs: number;
    covered: boolean;
    by_segment: Record<string, number>;
  };
};

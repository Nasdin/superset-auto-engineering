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
  repository: string;
  repositories: string[];
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

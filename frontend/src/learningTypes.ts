import type { Job } from "./liveTypes";

export type Observation = {
  job_id: string;
  kind: string;
  status: string;
  title: string;
  summary: string;
  candidate_sha: string | null;
  pr_number: number | null;
  session_url: string | null;
  feedback_id?: string;
  previous_revision?: string | null;
  source_lesson_id?: string | null;
  author?: string;
  original_author?: string;
  attribution?: "operator_reported";
  reason?: string;
};
export type Lesson = {
  id: string;
  created: number;
  native_state: string;
  note_id: string | null;
  is_current?: boolean | null;
  observation: Observation;
};
export type LearningData = {
  repository: string;
  branch: string;
  sync: { state: string; at?: number; error?: string };
  lessons: Lesson[];
  contexts: {
    job_id: string;
    created: number;
    memories: {
      lesson_id: string;
      knowledge_id: string | null;
      observation: Observation;
    }[];
  }[];
  cohorts: { month: string; passed: number; failed: number }[];
  jobs: Job[];
};

/** Preserve the newest version per source without mutating polling data. */
export function latestObservations(lessons: Lesson[]) {
  const bySource = new Map<string, Lesson>();
  for (const lesson of [...lessons].sort((a, b) => b.created - a.created)) {
    if (lesson.observation.feedback_id && lesson.is_current === false) continue;
    const source = lesson.observation.feedback_id || lesson.observation.job_id;
    if (!bySource.has(source)) {
      bySource.set(source, lesson);
    }
  }
  return [...bySource.values()];
}

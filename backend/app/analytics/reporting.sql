CREATE SCHEMA IF NOT EXISTS reporting;
CREATE OR REPLACE VIEW reporting.pull_requests AS
WITH source AS (
 SELECT repository,number,data::jsonb AS doc FROM public.pull_requests
), normalized AS (
 SELECT repository,number,doc->>'title' AS title,doc->>'url' AS url,doc->>'author' AS author,
 doc->'labels' AS labels,doc->>'base' AS base,doc->>'state' AS state,
 (doc->>'created_at')::timestamptz AS created_at,(doc->>'merged_at')::timestamptz AS merged_at,
 (doc->>'closed_at')::timestamptz AS closed_at,
 EXISTS(SELECT 1 FROM public.jobs j WHERE j.pr_number=source.number AND j.kind IN ('repair','patch','dependency') AND split_part(j.dedup,':',2)=source.repository) AS tracked
 FROM source
)
SELECT *,lower(author)='dependabot[bot]' AS dependabot,
 CASE WHEN lower(title) ~ '\m(revert|rollback)\M' THEN 'revert'
 WHEN lower(author)='dependabot[bot]' OR lower(title) ~ '\m(deps|dependency|dependencies|bump)\M'
 OR EXISTS(SELECT 1 FROM jsonb_array_elements_text(labels) l WHERE lower(l) IN ('dependencies','.dependency','dependabot') OR lower(l) LIKE 'dependencies:%') THEN 'dependency'
 WHEN lower(title) ~ '^(fix|bugfix)(\M|\()' OR EXISTS(SELECT 1 FROM jsonb_array_elements_text(labels) l WHERE lower(l) IN ('#bug','bug','fix','bugfix','type:bug')) THEN 'fix'
 WHEN lower(title) ~ '^(feat|feature)(\M|\()' OR EXISTS(SELECT 1 FROM jsonb_array_elements_text(labels) l WHERE lower(l) IN ('enhancement','feature')) THEN 'feature'
 ELSE 'other' END AS category,
 CASE WHEN merged_at>=created_at THEN extract(epoch FROM (merged_at-created_at))/3600.0 END AS hours_to_merge
FROM normalized;

CREATE OR REPLACE VIEW reporting.selected_prs AS
SELECT s.selection_id,p.* FROM public.analytics_selections s JOIN reporting.pull_requests p ON p.repository=s.repository
WHERE (s.author='' OR s.author=p.author) AND (s.label='' OR p.labels ? s.label)
 AND (s.base='' OR s.base=p.base) AND (s.kind='' OR s.kind=p.category)
 AND (s.provenance='all' OR (s.provenance='tracked' AND p.tracked) OR (s.provenance='untracked' AND NOT p.tracked));

CREATE OR REPLACE VIEW reporting.windows AS
SELECT s.selection_id,s.repository,s.days,c.cohort,c.window_end,
 ((c.window_end-(s.days-1))::timestamp AT TIME ZONE 'UTC') AS starts_at,
 ((c.window_end+1)::timestamp AT TIME ZONE 'UTC') AS stops_at,
 COALESCE((status.data::jsonb->>'complete')::boolean,false)
 AND (status.data::jsonb->>'coverage_from')::date <= c.window_end-(s.days-1)
 AND (status.data::jsonb->>'last_success')::timestamptz >= ((c.window_end+1)::timestamp AT TIME ZONE 'UTC') AS covered
FROM public.analytics_selections s
CROSS JOIN LATERAL (VALUES ('Current',s.window_end::date),('Baseline',s.baseline_end::date)) c(cohort,window_end)
LEFT JOIN public.sync_status status ON status.repository=s.repository;

CREATE OR REPLACE VIEW reporting.cohorts AS
SELECT w.selection_id,w.repository,w.cohort,w.window_end,w.days,COALESCE(w.covered,false) AS history_covered,
 count(p.number) AS merged_prs,count(p.hours_to_merge) AS measured_prs,
 count(p.number)-count(p.hours_to_merge) AS invalid_durations,
 percentile_cont(0.5) WITHIN GROUP (ORDER BY p.hours_to_merge)::double precision AS median_hours,
 percentile_disc(0.75) WITHIN GROUP (ORDER BY p.hours_to_merge)::double precision AS p75_hours
FROM reporting.windows w LEFT JOIN reporting.selected_prs p ON p.selection_id=w.selection_id AND p.merged_at>=w.starts_at AND p.merged_at<w.stops_at
GROUP BY w.selection_id,w.repository,w.cohort,w.window_end,w.days,w.covered;

CREATE OR REPLACE VIEW reporting.comparison AS
SELECT c.selection_id,c.repository,c.merged_prs,c.measured_prs,c.median_hours AS current_median_hours,
 b.median_hours AS baseline_median_hours,b.measured_prs AS baseline_measured_prs,
 c.history_covered AND b.history_covered AS history_covered,
 CASE WHEN c.history_covered AND b.history_covered AND c.measured_prs>=5 AND b.measured_prs>=5 AND b.median_hours>0
 THEN (c.median_hours/b.median_hours-1)*100 END AS median_change_percent
FROM reporting.cohorts c JOIN reporting.cohorts b ON b.selection_id=c.selection_id AND b.cohort='Baseline' WHERE c.cohort='Current';

CREATE OR REPLACE VIEW reporting.trend AS
WITH periods AS (
 SELECT s.selection_id,s.repository,s.days,s.window_end::date-step.delta AS window_end,
 ((s.window_end::date-step.delta-(s.days-1))::timestamp AT TIME ZONE 'UTC') AS starts_at,
 ((s.window_end::date-step.delta+1)::timestamp AT TIME ZONE 'UTC') AS stops_at
 FROM public.analytics_selections s CROSS JOIN generate_series(0,182,7) step(delta)
), aggregates AS (
 SELECT p.selection_id,p.repository,p.window_end,p.days,count(r.hours_to_merge) AS measured_prs,
 percentile_cont(0.5) WITHIN GROUP (ORDER BY r.hours_to_merge)::double precision AS median_hours,
 COALESCE((status.data::jsonb->>'complete')::boolean,false)
 AND (status.data::jsonb->>'coverage_from')::date<=p.window_end-(p.days-1)
 AND (status.data::jsonb->>'last_success')::timestamptz>=p.stops_at AS history_covered
 FROM periods p LEFT JOIN reporting.selected_prs r ON r.selection_id=p.selection_id AND r.merged_at>=p.starts_at AND r.merged_at<p.stops_at
 LEFT JOIN public.sync_status status ON status.repository=p.repository
 GROUP BY p.selection_id,p.repository,p.window_end,p.days,p.stops_at,status.data
)
SELECT *,CASE WHEN history_covered THEN median_hours END AS covered_median_hours FROM aggregates;

CREATE OR REPLACE VIEW reporting.details AS
SELECT p.* FROM reporting.selected_prs p JOIN reporting.windows w ON p.selection_id=w.selection_id AND w.cohort='Current'
 WHERE p.merged_at>=w.starts_at AND p.merged_at<w.stops_at;

REVOKE ALL ON SCHEMA reporting FROM PUBLIC;
GRANT USAGE ON SCHEMA reporting TO cognition_reader;
GRANT SELECT ON reporting.comparison,reporting.cohorts,reporting.trend,reporting.details TO cognition_reader;

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
), classified AS (
SELECT *,lower(author)='dependabot[bot]' AS dependabot,
 CASE WHEN lower(title) ~ '\m(revert|rollback)\M' THEN 'revert'
 WHEN lower(author)='dependabot[bot]' OR lower(title) ~ '\m(deps|dependency|dependencies|bump)\M'
 OR EXISTS(SELECT 1 FROM jsonb_array_elements_text(labels) l WHERE lower(l) IN ('dependencies','.dependency','dependabot') OR lower(l) LIKE 'dependencies:%') THEN 'dependency'
 WHEN lower(title) ~ '^(fix|bugfix)(\M|\()' OR EXISTS(SELECT 1 FROM jsonb_array_elements_text(labels) l WHERE lower(l) IN ('#bug','bug','fix','bugfix','type:bug')) THEN 'fix'
 WHEN lower(title) ~ '^(feat|feature)(\M|\()' OR EXISTS(SELECT 1 FROM jsonb_array_elements_text(labels) l WHERE lower(l) IN ('enhancement','feature')) THEN 'feature'
 ELSE 'other' END AS category,
 CASE WHEN merged_at>=created_at THEN extract(epoch FROM (merged_at-created_at))/3600.0 END AS hours_to_merge
FROM normalized
)
SELECT c.*,
 doc->>'author_type' AS author_type,
 CASE WHEN doc->>'commits_count' ~ '^[0-9]+$' THEN (doc->>'commits_count')::bigint END AS commits_count,
 CASE WHEN doc->>'additions' ~ '^[0-9]+$' THEN (doc->>'additions')::bigint END AS additions,
 CASE WHEN doc->>'deletions' ~ '^[0-9]+$' THEN (doc->>'deletions')::bigint END AS deletions,
 CASE WHEN doc->>'changed_files' ~ '^[0-9]+$' THEN (doc->>'changed_files')::bigint END AS changed_files,
 (doc->>'first_review_at')::timestamptz AS first_review_at,
 CASE WHEN doc->>'rework_commits' ~ '^[0-9]+$' THEN (doc->>'rework_commits')::bigint END AS rework_commits,
 (doc->>'details_updated_at')::timestamptz AS details_updated_at,
 doc->>'enrichment_state' AS enrichment_state,
 (lower(COALESCE(doc->>'author_type',''))='bot' OR right(lower(COALESCE(c.author,'')),5)='[bot]') AS is_bot,
 CASE WHEN lower(COALESCE(doc->>'author_type',''))='bot' OR right(lower(COALESCE(c.author,'')),5)='[bot]' THEN 'Bots'
 WHEN c.category='fix' THEN 'Fixes' WHEN c.category='feature' THEN 'Features' ELSE 'Other' END AS segment
FROM classified c JOIN source USING(repository,number);

CREATE OR REPLACE VIEW reporting.selected_prs AS
SELECT s.selection_id,p.* FROM public.analytics_selections s JOIN reporting.pull_requests p ON p.repository=s.repository
WHERE (s.author='' OR s.author=p.author) AND (s.label='' OR p.labels ? s.label)
 AND (s.base='' OR s.base=p.base) AND (s.kind='' OR (s.kind='bot' AND p.is_bot) OR (s.kind<>'bot' AND s.kind=p.category))
 AND (s.provenance='all' OR (s.provenance='tracked' AND p.tracked) OR (s.provenance='untracked' AND NOT p.tracked));

-- Explicit month repairs override broad scan claims, including unverified gaps.
-- A retained month prefix remains valid while its later days are being fetched.
CREATE OR REPLACE FUNCTION reporting.history_covered(repo text, starts_on date, ends_on date)
RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
 WITH broad AS (
   SELECT COALESCE((
     SELECT COALESCE((s.data::jsonb->>'complete')::boolean,false)
       AND (s.data::jsonb->>'coverage_from')::date<=starts_on
       AND (s.data::jsonb->>'last_success')::timestamptz>=((ends_on+1)::timestamp AT TIME ZONE 'UTC')
     FROM public.sync_status s WHERE s.repository=repo
   ),false) AS covered
 )
 SELECT ends_on>=starts_on AND NOT EXISTS (
   SELECT 1 FROM generate_series(date_trunc('month',starts_on::timestamp),
     date_trunc('month',ends_on::timestamp),interval '1 month') m(month)
   CROSS JOIN broad
   LEFT JOIN public.analytics_months a ON a.repository=repo AND a.month=m.month::date::text
   WHERE CASE WHEN a.month IS NOT NULL THEN NOT COALESCE(
     a.covered_through::date>=LEAST(ends_on,(m.month+interval '1 month'-interval '1 day')::date),false)
     ELSE NOT broad.covered END
 )
$$;

CREATE OR REPLACE VIEW reporting.windows AS
SELECT s.selection_id,s.repository,s.days,c.cohort,c.window_end,
 ((c.window_end-(s.days-1))::timestamp AT TIME ZONE 'UTC') AS starts_at,
 ((c.window_end+1)::timestamp AT TIME ZONE 'UTC') AS stops_at,
 reporting.history_covered(s.repository,c.window_end-(s.days-1),c.window_end) AS covered
FROM public.analytics_selections s
CROSS JOIN LATERAL (VALUES ('Current',s.window_end::date),('Baseline',s.baseline_end::date)) c(cohort,window_end);

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
 reporting.history_covered(p.repository,p.window_end-(p.days-1),p.window_end) AS history_covered
 FROM periods p LEFT JOIN reporting.selected_prs r ON r.selection_id=p.selection_id AND r.merged_at>=p.starts_at AND r.merged_at<p.stops_at
 GROUP BY p.selection_id,p.repository,p.window_end,p.days,p.stops_at
)
SELECT *,CASE WHEN history_covered THEN median_hours END AS covered_median_hours FROM aggregates;

CREATE OR REPLACE VIEW reporting.details AS
SELECT p.* FROM reporting.selected_prs p JOIN reporting.windows w ON p.selection_id=w.selection_id AND w.cohort='Current'
 WHERE p.merged_at>=w.starts_at AND p.merged_at<w.stops_at;

-- These periods share the same selected PR population, including guest selection RLS.
-- Calendar months and rolling windows deliberately remain separate measures.
CREATE OR REPLACE VIEW reporting.impact_periods AS
SELECT s.selection_id,s.repository,'monthly'::text AS cadence,'Monthly'::text AS cohort,
 m.month::date AS month,m.month::date AS window_start,
 LEAST((m.month+interval '1 month'-interval '1 day')::date,s.window_end::date) AS window_end
FROM public.analytics_selections s
CROSS JOIN LATERAL generate_series(
 date_trunc('month',s.window_end::date::timestamp)-interval '6 months',
 date_trunc('month',s.window_end::date::timestamp),interval '1 month') m(month)
UNION ALL
SELECT s.selection_id,s.repository,'rolling','Rolling',NULL::date,
 s.window_end::date-step.delta-(s.days-1),s.window_end::date-step.delta
FROM public.analytics_selections s CROSS JOIN generate_series(0,182,7) step(delta)
UNION ALL
SELECT s.selection_id,s.repository,'categories',c.cohort,NULL::date,c.window_end-(s.days-1),c.window_end
FROM public.analytics_selections s
CROSS JOIN LATERAL (VALUES ('Current',s.window_end::date),('Baseline',s.baseline_end::date)) c(cohort,window_end);

CREATE OR REPLACE VIEW reporting.impact_aggregates AS
SELECT w.selection_id,w.repository,w.cadence,w.cohort,w.month,w.window_start,w.window_end,
 w.window_end-w.window_start+1 AS days,g.segment,
 count(p.number) AS merged_prs,count(p.hours_to_merge) AS measured_prs,
 count(p.commits_count) AS commits_samples,
 count(p.number) FILTER (WHERE p.additions IS NOT NULL AND p.deletions IS NOT NULL) AS code_samples,
 count(p.rework_commits) AS rework_samples,
 avg(p.commits_count)::double precision AS avg_commits,
 percentile_cont(0.5) WITHIN GROUP (ORDER BY p.hours_to_merge)::double precision AS median_hours,
 avg(p.rework_commits)::double precision AS avg_rework,
 sum(p.additions) FILTER (WHERE p.additions IS NOT NULL AND p.deletions IS NOT NULL) AS additions,
 sum(p.deletions) FILTER (WHERE p.additions IS NOT NULL AND p.deletions IS NOT NULL) AS deletions,
 avg(p.additions+p.deletions)::double precision AS avg_lines_changed,
 reporting.history_covered(w.repository,w.window_start,w.window_end) AS history_covered,
 sum(p.hours_to_merge)::double precision AS total_hours
FROM reporting.impact_periods w
CROSS JOIN (VALUES ('Bots'),('Fixes'),('Features'),('Other')) g(segment)
LEFT JOIN reporting.selected_prs p ON p.selection_id=w.selection_id AND p.segment=g.segment
 AND p.merged_at>=(w.window_start::timestamp AT TIME ZONE 'UTC')
 AND p.merged_at<((w.window_end+1)::timestamp AT TIME ZONE 'UTC')
GROUP BY w.selection_id,w.repository,w.cadence,w.cohort,w.month,w.window_start,w.window_end,g.segment;

CREATE OR REPLACE VIEW reporting.impact_monthly AS
SELECT * FROM reporting.impact_aggregates WHERE cadence='monthly';
CREATE OR REPLACE VIEW reporting.impact_rolling AS
SELECT * FROM reporting.impact_aggregates WHERE cadence='rolling';
CREATE OR REPLACE VIEW reporting.impact_categories AS
SELECT * FROM reporting.impact_aggregates WHERE cadence='categories';

-- Axis-only NULL rows extend the chart to the rollout marker without creating
-- post-rollout observations. Actual analysis views above never include these rows.
CREATE OR REPLACE VIEW reporting.impact_monthly_chart AS
SELECT selection_id,month AS chart_date,segment,
 CASE WHEN history_covered THEN median_hours END AS median_hours,
 CASE WHEN history_covered THEN avg_commits END AS avg_commits,
 CASE WHEN history_covered THEN avg_rework END AS avg_rework,
 CASE WHEN history_covered THEN avg_lines_changed END AS avg_lines_changed
FROM reporting.impact_monthly
UNION ALL
SELECT s.selection_id,CASE WHEN abs(s.window_end::date-DATE '2026-09-21')<=7
 THEN GREATEST(s.window_end::date,DATE '2026-09-24') ELSE s.window_end::date END,g.segment,
 NULL::double precision,NULL::double precision,NULL::double precision,NULL::double precision
FROM public.analytics_selections s CROSS JOIN (VALUES ('Bots'),('Fixes'),('Features'),('Other')) g(segment);
CREATE OR REPLACE VIEW reporting.impact_rolling_chart AS
SELECT selection_id,window_end AS chart_date,segment,
 CASE WHEN history_covered THEN median_hours END AS median_hours,
 CASE WHEN history_covered THEN avg_commits END AS avg_commits,
 CASE WHEN history_covered THEN avg_rework END AS avg_rework,
 CASE WHEN history_covered THEN avg_lines_changed END AS avg_lines_changed
FROM reporting.impact_rolling
UNION ALL
SELECT s.selection_id,CASE WHEN abs(s.window_end::date-DATE '2026-09-21')<=7
 THEN GREATEST(s.window_end::date,DATE '2026-09-24') ELSE s.window_end::date END,g.segment,
 NULL::double precision,NULL::double precision,NULL::double precision,NULL::double precision
FROM public.analytics_selections s CROSS JOIN (VALUES ('Bots'),('Fixes'),('Features'),('Other')) g(segment);

-- A month is one non-overlapping UTC merge-date cohort. Totals represent elapsed
-- PR time, not engineer labour: overlapping PR durations are intentionally summed.
-- Blank periods are incomplete. Only fully covered empty months measure zero.
CREATE OR REPLACE VIEW reporting.impact_total_monthly_chart AS
SELECT selection_id,month AS chart_date,'All selected PRs'::text AS segment,
 CASE WHEN bool_and(history_covered) AND sum(measured_prs)=sum(merged_prs)
 THEN COALESCE(sum(total_hours),0)::double precision END AS total_hours
FROM reporting.impact_monthly
GROUP BY selection_id,month
UNION ALL
SELECT s.selection_id,CASE WHEN abs(s.window_end::date-DATE '2026-09-21')<=7
 THEN GREATEST(s.window_end::date,DATE '2026-09-24') ELSE s.window_end::date END,
 'All selected PRs'::text,NULL::double precision
FROM public.analytics_selections s;

REVOKE EXECUTE ON FUNCTION reporting.history_covered(text,date,date) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION reporting.history_covered(text,date,date) TO cognition_reader;
REVOKE ALL ON SCHEMA reporting FROM PUBLIC;
GRANT USAGE ON SCHEMA reporting TO cognition_reader;
GRANT SELECT ON reporting.comparison,reporting.cohorts,reporting.trend,reporting.details,
 reporting.impact_monthly,reporting.impact_rolling,reporting.impact_categories,
 reporting.impact_monthly_chart,reporting.impact_rolling_chart,
 reporting.impact_total_monthly_chart TO cognition_reader;

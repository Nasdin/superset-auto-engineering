"""Idempotent Superset metadata provisioning; only curated reporting views are exposed."""

import json
import os
import time
from datetime import datetime
from pathlib import Path
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from superset.app import create_app
from superset import db, security_manager


def database_url(user, password, database):
    return URL.create(
        "postgresql+psycopg2",
        username=user,
        password=password,
        host=os.getenv("POSTGRES_HOST", "postgres"),
        database=database,
    )


def provision():
    chart_cache_seconds = max(1, int(os.getenv("ANALYTICS_CHART_CACHE_SECONDS", "300")))
    engine = create_engine(
        database_url("cognition_app", os.environ["POSTGRES_APP_PASSWORD"], "cognition"),
        hide_parameters=True,
    )
    with engine.begin() as connection:
        for statement in Path("/app/cognition/reporting.sql").read_text().split(";"):
            if statement.strip():
                connection.execute(text(statement))
    admin = security_manager.find_user(username="cognition-admin")
    if not admin:
        admin = security_manager.add_user(
            "cognition-admin",
            "Cognition",
            "Admin",
            "admin@localhost",
            role=security_manager.find_role("Admin"),
            password=os.environ["ANALYTICS_SUPERSET_ADMIN_PASSWORD"],
        )
    guest = security_manager.find_role("CognitionGuest") or security_manager.add_role(
        "CognitionGuest"
    )
    guest.permissions = [
        p
        for permission, view in security_manager.PUBLIC_ROLE_PERMISSIONS
        if (p := security_manager.find_permission_view_menu(permission, view))
    ]
    issuer = security_manager.find_role("CognitionIssuer") or security_manager.add_role(
        "CognitionIssuer"
    )
    issuer.permissions = [
        security_manager.find_permission_view_menu(name, "SecurityRestApi")
        for name in ("can_grant_guest_token", "can_read")
    ]
    if not security_manager.find_user(username="cognition-issuer"):
        security_manager.add_user(
            "cognition-issuer",
            "Cognition",
            "Issuer",
            "issuer@localhost",
            role=issuer,
            password=os.environ["ANALYTICS_SUPERSET_SERVICE_PASSWORD"],
        )
    database = (
        db.session.query(Database)
        .filter_by(database_name="Superset engineering · Postgres")
        .one_or_none()
    )
    if database is None:
        database = Database(database_name="Superset engineering · Postgres")
        db.session.add(database)
    database.set_sqlalchemy_uri(
        database_url(
            "cognition_reader", os.environ["POSTGRES_READER_PASSWORD"], "cognition"
        ).render_as_string(hide_password=False)
    )
    # Superset uses NullPool for chart engines, so QueuePool-only settings here
    # would crash queries. Concurrent chart connections are bounded by Gunicorn
    # threads (three per process); driver deadlines bound each operation.
    extra = json.loads(database.extra or "{}")
    extra["engine_params"] = {
        "connect_args": {
            "connect_timeout": 5,
            "options": "-c statement_timeout=30000 -c lock_timeout=5000 -c jit=off",
        },
    }
    database.extra = json.dumps(extra)
    database.cache_timeout = chart_cache_seconds
    database.expose_in_sqllab = False
    database.allow_dml = False
    database.allow_ctas = False
    database.allow_cvas = False
    database.allow_file_upload = False
    db.session.flush()
    tables = {}
    for name in (
        "comparison",
        "cohorts",
        "trend",
        "details",
        "impact_monthly",
        "impact_rolling",
        "impact_categories",
        "impact_monthly_chart",
        "impact_rolling_chart",
        "impact_total_monthly_chart",
        "impact_segment_total_monthly_chart",
        "focus_monthly_chart",
        "focus_weekly_chart",
    ):
        table = (
            db.session.query(SqlaTable)
            .filter_by(database_id=database.id, schema="reporting", table_name=name)
            .one_or_none()
        )
        if table is None:
            table = SqlaTable(
                table_name=name, schema="reporting", database=database, owners=[admin]
            )
            db.session.add(table)
        db.session.flush()
        table.cache_timeout = chart_cache_seconds
        table.fetch_metadata()
        if name in {
            "trend",
            "cohorts",
            "impact_monthly",
            "impact_rolling",
            "impact_categories",
        }:
            table.main_dttm_col = "window_end"
        if name.endswith("_chart"):
            table.main_dttm_col = "chart_date"
        for column in table.columns:
            column.verbose_name = column.column_name.replace("_", " ").capitalize()
        tables[name] = table
    # Native events are rendered as ECharts vertical markLines. This records a
    # rollout date, not an observed improvement or a synthetic post-rollout value.
    layer = db.session.query(AnnotationLayer).filter_by(name="Cognition rollout").one_or_none()
    if layer is None:
        layer = AnnotationLayer(name="Cognition rollout", descr="Recorded deployment date")
        db.session.add(layer)
    db.session.flush()
    event = db.session.query(Annotation).filter_by(layer_id=layer.id).first()
    if event is None:
        event = Annotation(layer=layer)
        db.session.add(event)
    event.start_dttm = datetime(2026, 9, 21)
    event.end_dttm = datetime(2026, 9, 21)
    event.short_descr = "21 Sep 2026"
    event.long_descr = ""
    annotation = {
        "name": "System introduced",
        "annotationType": "EVENT",
        "sourceType": "NATIVE",
        "value": layer.id,
        "show": True,
        "showLabel": True,
        "showMarkers": False,
        "color": "#59677b",
        "style": "dotted",
        "width": 2,
    }
    annotation_read = security_manager.find_permission_view_menu("can_read", "Annotation")
    if annotation_read and annotation_read not in guest.permissions:
        guest.permissions.append(annotation_read)

    def chart_for(name, view, metric_name=None, columns=None):
        table = tables[view]
        viz = "echarts_timeseries_line" if metric_name else "table"
        chart = (
            db.session.query(Slice)
            .filter_by(slice_name=name, datasource_id=table.id, datasource_type="table")
            .one_or_none()
        )
        if chart is None:
            chart = Slice(
                slice_name=name,
                datasource_type="table",
                datasource_id=table.id,
                owners=[admin],
            )
            db.session.add(chart)
        params = {
            "datasource": f"{table.id}__table",
            "viz_type": viz,
            "time_range": "No filter",
            "adhoc_filters": [],
            "row_limit": 1000,
            "extra_form_data": {},
        }
        query = {
            "time_range": "No filter",
            "filters": [],
            "extras": {"having": "", "where": ""},
            "row_limit": 1000,
            "columns": [],
            "metrics": [],
            "orderby": [],
        }
        if metric_name:
            metric = next((m for m in table.metrics if m.metric_name == metric_name), None)
            if metric is None:
                metric = SqlMetric(metric_name=metric_name, expression=f"MAX({metric_name})")
                table.metrics.append(metric)
            metric.expression = f"MAX({metric_name})"
            params.update(
                x_axis="chart_date",
                granularity_sqla="chart_date",
                time_grain_sqla="P1D",
                metrics=[metric_name],
                groupby=["segment"],
                show_legend=True,
                legendType="scroll",
                legendOrientation="bottom",
                rich_tooltip=True,
                y_axis_format=",.1f",
                x_axis_time_format="%d %b" if view == "focus_weekly_chart" else "%b %Y",
                show_empty_columns=True,
                annotation_layers=[
                    {**annotation, "showLabel": False} if view.startswith("focus_") else annotation
                ],
                markerEnabled=True,
                markerSize=4,
                truncate_metric=True,
                forecastEnabled=False,
                color_scheme="supersetColors",
                seriesType="line",
                stack=None,
                area=False,
            )
            query.update(
                columns=[
                    {
                        "timeGrain": "P1D",
                        "columnType": "BASE_AXIS",
                        "sqlExpression": "chart_date",
                        "label": "chart_date",
                        "expressionType": "SQL",
                        "isColumnReference": True,
                    },
                    "segment",
                ],
                granularity="chart_date",
                metrics=[metric_name],
                series_columns=["segment"],
                annotation_layers=[
                    {**annotation, "showLabel": False} if view.startswith("focus_") else annotation
                ],
                post_processing=[
                    {
                        "operation": "pivot",
                        "options": {
                            "index": ["chart_date"],
                            "columns": ["segment"],
                            "aggregates": {metric_name: {"operator": "mean"}},
                            "drop_missing_columns": False,
                        },
                    },
                    {"operation": "flatten"},
                ],
            )
            chart.description = (
                "Merged PRs grouped by explicit change type, with bot authors counted only in Bots. "
                "Missing enrichment remains blank; it is never measured zero. The dotted line "
                "marks 2026-09-21, not a proven effect. An axis-only null row keeps the marker visible."
            )
        else:
            params.update(
                query_mode="raw",
                all_columns=columns,
                show_cell_bars=False,
                order_by_cols=[],
                page_length=15,
                include_search=True,
                table_timestamp_format="%Y-%m-%d",
                column_config={
                    **{
                        c: {"d3NumberFormat": ",.2f"}
                        for c in (
                            "median_hours",
                            "hours_to_merge",
                            "total_hours",
                            "segment_total_hours",
                            "avg_commits",
                            "avg_rework",
                            "avg_lines_changed",
                        )
                    },
                    "url": {"linkType": "url", "linkTarget": "_blank"},
                },
            )
            query["columns"] = columns
        db.session.flush()
        params["slice_id"] = chart.id
        chart.cache_timeout = chart_cache_seconds
        chart.viz_type = viz
        chart.params = json.dumps(params)
        query_context = {
            "datasource": {"id": table.id, "type": "table"},
            "queries": [query],
            "force": False,
            "result_format": "json",
            "result_type": "full",
            "form_data": params,
        }
        # Validate against the installed Superset version before publishing any
        # charts, including required annotation fields not used by event lines.
        errors = ChartDataQueryContextSchema().validate(query_context)
        if errors:
            raise ValueError(f"Invalid Superset chart configuration for {name}: {errors}")
        chart.query_context = json.dumps(query_context)
        return chart

    chart_for(
        "Change categories · comparison",
        "impact_categories",
        columns=[
            "cohort",
            "segment",
            "window_start",
            "window_end",
            "merged_prs",
            "measured_prs",
            "median_hours",
            "commits_samples",
            "avg_commits",
            "rework_samples",
            "avg_rework",
            "code_samples",
            "additions",
            "deletions",
            "avg_lines_changed",
            "history_covered",
        ],
    )
    detail_chart = chart_for(
        "Merged changes · current window",
        "details",
        columns=[
            "number",
            "title",
            "author",
            "segment",
            "category",
            "classification_reason",
            "tracked",
            "merged_at",
            "hours_to_merge",
            "commits_count",
            "rework_commits",
            "additions",
            "deletions",
            "changed_files",
            "first_review_at",
            "enrichment_state",
            "url",
        ],
    )
    measures = [
        ("Hours to merge", "median_hours"),
        ("Commits per PR", "avg_commits"),
        ("Rework after review", "avg_rework"),
        ("Lines changed per PR", "avg_lines_changed"),
    ]
    dashboards = {}
    chart_ids = {}
    # Superset calculates canvas pixels from the persisted grid column count.
    # CSS card stretching cannot change those React width props; mobile embeds
    # therefore get their own native 12-column layout, sharing the same charts.
    layouts = [
        (cadence, mobile, "overview")
        for cadence in ("monthly", "rolling")
        for mobile in (False, True)
    ]
    layouts += [
        (cadence, mobile, panel)
        for panel in ("delivery", "rework")
        for cadence in ("monthly", "weekly")
        for mobile in (False, True)
    ]
    for cadence, mobile, panel in layouts:
        focused = panel != "overview"
        key = (
            f"{panel}_{cadence}_{'mobile' if mobile else 'desktop'}"
            if focused
            else cadence + ("_mobile" if mobile else "")
        )
        if focused:
            focus_measures = (
                [
                    ("Commits per PR", "avg_commits"),
                    ("Median hours to merge", "median_hours"),
                    ("Commits after first review", "avg_rework"),
                    ("Lines changed per PR", "avg_lines_changed"),
                ]
                if panel == "delivery"
                else [
                    ("Commits after first review", "avg_rework"),
                    ("Lines changed per PR", "avg_lines_changed"),
                    ("Lines added per PR", "avg_additions"),
                    ("Lines removed per PR", "avg_deletions"),
                ]
            )
            charts = [
                chart_for(name, f"focus_{cadence}_chart", metric) for name, metric in focus_measures
            ]
        else:
            charts = [
                chart_for(name, f"impact_{cadence}_chart", metric) for name, metric in measures
            ]
        total_chart = chart_for(
            "Total hours before merge · calendar month",
            "impact_total_monthly_chart",
            "total_hours",
        )
        total_chart.description = (
            "Sum of elapsed hours from PR creation to merge for all selected PRs merged "
            "in each UTC calendar month. Always monthly, including in the rolling dashboard. "
            "A partial final month ends on the selected date. Overlapping PR durations are "
            "summed: this is neither working hours nor time saved. Uncovered months or "
            "months containing invalid durations stay blank; fully covered empty months are zero."
        )
        category_total = chart_for(
            "Total merge hours by work type · calendar month",
            "impact_segment_total_monthly_chart",
            "segment_total_hours",
        )
        category_total.description = (
            "Sum of elapsed creation-to-merge hours by UTC merge month and mutually exclusive "
            "work type. Bot authors belong only to Bots. Explicit title intent takes precedence "
            "over broad labels. Documentation, dependencies, refactoring, tests, build/CI, "
            "performance, releases, reverts and maintenance are separately named. Titles "
            "without reliable signals remain Needs classification. Missing history or invalid "
            "durations stay blank. Overlapping waits count separately, not as labour saved."
        )
        # Lead with the requested category total, full width in both layouts.
        if focused:
            if panel == "delivery":
                charts.append(
                    chart_for(
                        "Total merge hours by work type · calendar month",
                        "focus_monthly_chart",
                        "segment_total_hours",
                    )
                )
        else:
            charts = [category_total, *charts, total_chart, detail_chart]
        slug = (
            "superset-engineering"
            + ("-rolling" if cadence == "rolling" else "")
            + ("-mobile" if mobile else "")
            + (f"-{panel}-{cadence}" if focused else "")
        )
        dashboard = db.session.query(Dashboard).filter_by(slug=slug).one_or_none()
        if dashboard is None:
            dashboard = Dashboard(slug=slug, owners=[admin])
            db.session.add(dashboard)
        dashboard.dashboard_title = f"Superset analyzing Superset · {cadence}" + (
            " · mobile" if mobile else ""
        )
        dashboard.slices = charts
        dashboard.published = True
        dashboard.css = (
            '[data-test="span-title"] {font-weight:600;font-size:15px;color:#101b2d} .dashboard-content {background:#fcfcfb} .dashboard-component-chart-holder {border:1px solid #dfe4eb;border-radius:6px;}'
            if focused
            else ""
        )
        positions = {
            "DASHBOARD_VERSION_KEY": "v2",
            "ROOT_ID": {"id": "ROOT_ID", "type": "ROOT", "children": ["GRID_ID"]},
            "GRID_ID": {
                "id": "GRID_ID",
                "type": "GRID",
                "parents": ["ROOT_ID"],
                "children": [],
            },
        }
        rows = (
            [[chart] for chart in charts]
            if mobile
            else (
                [charts[i : i + 2] for i in range(0, len(charts), 2)]
                if focused
                else (charts[:1], charts[1:3], charts[3:5], charts[5:6], charts[6:7])
            )
        )
        for row_number, row_charts in enumerate(rows):
            row_id = f"ROW-{row_number}"
            positions["GRID_ID"]["children"].append(row_id)
            positions[row_id] = {
                "id": row_id,
                "type": "ROW",
                "parents": ["ROOT_ID", "GRID_ID"],
                "children": [],
                "meta": {"background": "BACKGROUND_TRANSPARENT"},
            }
            for chart in row_charts:
                chart_id = f"CHART-{chart.id}"
                positions[row_id]["children"].append(chart_id)
                positions[chart_id] = {
                    "id": chart_id,
                    "type": "CHART",
                    "parents": ["ROOT_ID", "GRID_ID", row_id],
                    "children": [],
                    "meta": {
                        "chartId": chart.id,
                        "sliceName": chart.slice_name,
                        "width": 12 // len(row_charts),
                        "height": 32 if focused else 46 if chart is detail_chart else 42,
                    },
                }
        dashboard.position_json = json.dumps(positions)
        dashboard.json_metadata = json.dumps(
            {
                "refresh_frequency": 0,
                "cross_filters_enabled": False,
                "native_filter_configuration": [],
                "label_colors": {
                    "Bots": "#df8717",
                    "Fixes": "#009880",
                    "Features": "#2583ff",
                    "Dependencies": "#8561b5",
                    "Documentation": "#8b7355",
                    "Refactoring": "#b85e7d",
                    "Tests": "#57968c",
                    "Build & CI": "#697b98",
                    "Performance": "#55863e",
                    "Releases": "#c06e36",
                    "Reverts": "#b34747",
                    "Maintenance": "#7c8580",
                    "Needs classification": "#434843",
                },
            }
        )
        db.session.flush()
        embedded = EmbeddedDashboardDAO.upsert(
            dashboard, os.environ["SUPERSET_ALLOWED_ORIGINS"].split(",")
        )
        # A newly embedded dashboard receives its UUID on SQLAlchemy flush.
        # Persisting str(None) here would break the first rolling-dashboard login.
        db.session.flush()
        dashboards[key] = str(embedded.uuid)
        chart_ids[key] = [c.id for c in charts]
    db.session.commit()
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO memory(key,value,updated) VALUES('superset_dashboard',:value,:now) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated=excluded.updated"
            ),
            {
                "value": json.dumps(
                    {
                        "dashboard_id": dashboards["monthly"],
                        "rolling_dashboard_id": dashboards["rolling"],
                        "mobile_dashboard_id": dashboards["monthly_mobile"],
                        "mobile_rolling_dashboard_id": dashboards["rolling_mobile"],
                        **{
                            key: value
                            for key, value in dashboards.items()
                            if key.startswith(("delivery_", "rework_"))
                        },
                        "dashboard_path": "/superset/dashboard/superset-engineering/",
                        "rolling_dashboard_path": "/superset/dashboard/superset-engineering-rolling/",
                        "mobile_dashboard_path": "/superset/dashboard/superset-engineering-mobile/",
                        "mobile_rolling_dashboard_path": "/superset/dashboard/superset-engineering-rolling-mobile/",
                        "chart_ids": chart_ids["monthly"],
                        "rolling_chart_ids": chart_ids["rolling"],
                    }
                ),
                "now": time.time(),
            },
        )
    engine.dispose()
    print(
        json.dumps(
            {
                "dashboards": dashboards,
                "charts_per_dashboard": {key: len(ids) for key, ids in chart_ids.items()},
                "datasets": len(tables),
            }
        )
    )


if __name__ == "__main__":
    with create_app().app_context():
        from superset.charts.schemas import ChartDataQueryContextSchema
        from superset.models.annotations import Annotation, AnnotationLayer
        from superset.models.core import Database
        from superset.connectors.sqla.models import SqlaTable, SqlMetric
        from superset.models.slice import Slice
        from superset.models.dashboard import Dashboard
        from superset.daos.dashboard import EmbeddedDashboardDAO

        provision()

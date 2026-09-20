"""Idempotent Superset metadata provisioning; only curated reporting views are exposed."""

import json
import os
import time
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
    database.expose_in_sqllab = False
    database.allow_dml = False
    database.allow_ctas = False
    database.allow_cvas = False
    database.allow_file_upload = False
    db.session.flush()
    tables = {}
    for name in ("comparison", "cohorts", "trend", "details"):
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
        table.fetch_metadata()
        if name in {"trend", "cohorts"}:
            table.main_dttm_col = "window_end"
        for column in table.columns:
            column.verbose_name = column.column_name.replace("_", " ").capitalize()
        tables[name] = table
    definitions = [
        (
            "Current median · hours",
            "comparison",
            "big_number_total",
            "current_median_hours",
            None,
        ),
        (
            "Baseline median · hours",
            "comparison",
            "big_number_total",
            "baseline_median_hours",
            None,
        ),
        (
            "Median change · %",
            "comparison",
            "big_number_total",
            "median_change_percent",
            None,
        ),
        (
            "Rolling merge time · hours",
            "trend",
            "echarts_timeseries_line",
            "covered_median_hours",
            None,
        ),
        (
            "Comparable windows & sample sizes",
            "cohorts",
            "table",
            None,
            [
                "cohort",
                "window_end",
                "days",
                "merged_prs",
                "measured_prs",
                "invalid_durations",
                "median_hours",
                "p75_hours",
                "history_covered",
            ],
        ),
        (
            "Merged changes · current window",
            "details",
            "table",
            None,
            [
                "number",
                "title",
                "author",
                "category",
                "dependabot",
                "tracked",
                "merged_at",
                "hours_to_merge",
                "url",
            ],
        ),
    ]
    charts = []
    for name, view, viz, metric_name, columns in definitions:
        table = tables[view]
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
            metric = next(
                (m for m in table.metrics if m.metric_name == metric_name), None
            )
            if metric is None:
                metric = SqlMetric(
                    metric_name=metric_name, expression=f"MAX({metric_name})"
                )
                table.metrics.append(metric)
            metric.expression = f"MAX({metric_name})"
            query["metrics"] = [metric_name]
            if viz == "big_number_total":
                params.update(
                    metric=metric_name, y_axis_format=",.2f", show_trend_line=False
                )
            else:
                params.update(
                    x_axis="window_end",
                    granularity_sqla="window_end",
                    time_grain_sqla="P1D",
                    metrics=[metric_name],
                    groupby=[],
                    show_legend=False,
                    rich_tooltip=True,
                    y_axis_format=",.1f",
                    x_axis_time_format="%Y-%m-%d",
                )
                query.update(
                    columns=[
                        {
                            "timeGrain": "P1D",
                            "columnType": "BASE_AXIS",
                            "sqlExpression": "window_end",
                            "label": "window_end",
                            "expressionType": "SQL",
                            "isColumnReference": True,
                        }
                    ],
                    granularity="window_end",
                    orderby=[[metric_name, False]],
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
                        for c in ("median_hours", "p75_hours", "hours_to_merge")
                    },
                    "url": {"linkType": "url", "linkTarget": "_blank"},
                },
            )
            query["columns"] = columns
        db.session.flush()
        params["slice_id"] = chart.id
        chart.viz_type = viz
        chart.params = json.dumps(params)
        chart.query_context = json.dumps(
            {
                "datasource": {"id": table.id, "type": "table"},
                "queries": [query],
                "result_format": "json",
                "result_type": "full",
                "form_data": params,
            }
        )
        charts.append(chart)
    dashboard = (
        db.session.query(Dashboard).filter_by(slug="superset-engineering").one_or_none()
    )
    if dashboard is None:
        dashboard = Dashboard(
            dashboard_title="Superset analyzing Superset",
            slug="superset-engineering",
            owners=[admin],
        )
        db.session.add(dashboard)
    dashboard.slices = charts
    dashboard.published = True
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
    for row_number, row_charts in enumerate(
        (charts[:3], charts[3:4], charts[4:5], charts[5:6])
    ):
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
                    "height": (24, 55, 28, 60)[row_number],
                },
            }
    dashboard.position_json = json.dumps(positions)
    dashboard.json_metadata = json.dumps(
        {
            "refresh_frequency": 0,
            "cross_filters_enabled": False,
            "native_filter_configuration": [],
        }
    )
    db.session.flush()
    embedded = EmbeddedDashboardDAO.upsert(
        dashboard, os.environ["SUPERSET_ALLOWED_ORIGINS"].split(",")
    )
    db.session.commit()
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO memory(key,value,updated) VALUES('superset_dashboard',:value,:now) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated=excluded.updated"
            ),
            {
                "value": json.dumps(
                    {
                        "dashboard_id": str(embedded.uuid),
                        "dashboard_path": "/superset/dashboard/superset-engineering/",
                        "chart_ids": [c.id for c in charts],
                    }
                ),
                "now": time.time(),
            },
        )
    engine.dispose()
    print(
        json.dumps(
            {
                "dashboard_id": str(embedded.uuid),
                "charts": len(charts),
                "datasets": len(tables),
            }
        )
    )


if __name__ == "__main__":
    with create_app().app_context():
        from superset.models.core import Database
        from superset.connectors.sqla.models import SqlaTable, SqlMetric
        from superset.models.slice import Slice
        from superset.models.dashboard import Dashboard
        from superset.daos.dashboard import EmbeddedDashboardDAO

        provision()

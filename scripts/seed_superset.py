"""Run inside the isolated Superset container; reads credentials from its environment."""

import os
from sqlalchemy import create_engine, text
from superset.app import create_app
from superset import db, security_manager

app = create_app()
with app.app_context():
    from superset.models.core import Database

    if not security_manager.find_user(username="validator"):
        security_manager.add_user(
            username="validator",
            first_name="Cognition",
            last_name="Validator",
            email="validator@example.invalid",
            role=security_manager.find_role("Admin"),
            password=os.environ["VALIDATION_ADMIN_PASSWORD"],
        )
    uri = (
        "mysql+pymysql://root:"
        + os.environ["MYSQL_ROOT_PASSWORD"]
        + "@mysql:3306/validation"
    )
    connection = create_engine(uri)
    with connection.begin() as con:
        con.execute(
            text(
                "CREATE TABLE IF NOT EXISTS grain_fixture (dt DATETIME PRIMARY KEY, value INTEGER NOT NULL)"
            )
        )
        con.execute(
            text(
                "INSERT IGNORE INTO grain_fixture VALUES ('2026-09-18 00:00:00',1),('2026-09-18 08:15:30',2),('2026-09-18 23:59:59',3)"
            )
        )
    database = (
        db.session.query(Database)
        .filter_by(database_name="Cognition MySQL")
        .one_or_none()
    )
    if not database:
        database = Database(
            database_name="Cognition MySQL",
            sqlalchemy_uri=uri,
            expose_in_sqllab=True,
            allow_ctas=False,
            allow_cvas=False,
            allow_dml=False,
        )
        db.session.add(database)
        db.session.commit()
    print(
        "Isolated validator account and MySQL fixture are ready; credentials omitted."
    )

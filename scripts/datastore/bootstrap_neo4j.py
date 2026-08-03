"""
AC-2: Create Neo4j constraints and indexes for all required node labels.
Idempotent — uses IF NOT EXISTS syntax (Neo4j 5+).

Usage:
    python scripts/datastore/bootstrap_neo4j.py
"""
from __future__ import annotations

import os
import sys

from neo4j import Driver, GraphDatabase

NEO4J_URI      = os.environ.get("NEO4J_URI",      "bolt://contextiq-neo4j.contextiq-data.svc.cluster.local:7687")
NEO4J_USERNAME = os.environ.get("NEO4J_USERNAME", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "")

# ── Schema definitions ──────────────────────────────────────────────────────
# Each entry: (constraint_name, cypher_statement)
CONSTRAINTS: list[tuple[str, str]] = [
    # Service: unique id; composite unique (name, namespace)
    (
        "constraint_service_id",
        "CREATE CONSTRAINT constraint_service_id IF NOT EXISTS "
        "FOR (s:Service) REQUIRE s.id IS UNIQUE",
    ),
    (
        "constraint_service_name_ns",
        "CREATE CONSTRAINT constraint_service_name_ns IF NOT EXISTS "
        "FOR (s:Service) REQUIRE (s.name, s.namespace) IS UNIQUE",
    ),
    # Repository: unique id and full_name
    (
        "constraint_repo_id",
        "CREATE CONSTRAINT constraint_repo_id IF NOT EXISTS "
        "FOR (r:Repository) REQUIRE r.id IS UNIQUE",
    ),
    (
        "constraint_repo_full_name",
        "CREATE CONSTRAINT constraint_repo_full_name IF NOT EXISTS "
        "FOR (r:Repository) REQUIRE r.full_name IS UNIQUE",
    ),
    # Developer: unique id and email
    (
        "constraint_developer_id",
        "CREATE CONSTRAINT constraint_developer_id IF NOT EXISTS "
        "FOR (d:Developer) REQUIRE d.id IS UNIQUE",
    ),
    (
        "constraint_developer_email",
        "CREATE CONSTRAINT constraint_developer_email IF NOT EXISTS "
        "FOR (d:Developer) REQUIRE d.email IS UNIQUE",
    ),
    # Incident: unique id
    (
        "constraint_incident_id",
        "CREATE CONSTRAINT constraint_incident_id IF NOT EXISTS "
        "FOR (i:Incident) REQUIRE i.id IS UNIQUE",
    ),
]

# Each entry: (index_name, cypher_statement)
INDEXES: list[tuple[str, str]] = [
    ("index_service_name",
     "CREATE INDEX index_service_name IF NOT EXISTS FOR (s:Service) ON (s.name)"),
    ("index_service_namespace",
     "CREATE INDEX index_service_namespace IF NOT EXISTS FOR (s:Service) ON (s.namespace)"),
    ("index_repo_language",
     "CREATE INDEX index_repo_language IF NOT EXISTS FOR (r:Repository) ON (r.primary_language)"),
    ("index_developer_team",
     "CREATE INDEX index_developer_team IF NOT EXISTS FOR (d:Developer) ON (d.team)"),
    ("index_incident_severity",
     "CREATE INDEX index_incident_severity IF NOT EXISTS FOR (i:Incident) ON (i.severity)"),
    ("index_incident_status",
     "CREATE INDEX index_incident_status IF NOT EXISTS FOR (i:Incident) ON (i.status)"),
    ("index_incident_created_at",
     "CREATE INDEX index_incident_created_at IF NOT EXISTS FOR (i:Incident) ON (i.created_at)"),
    # Composite: service + severity for dependency-impact queries
    (
        "index_incident_service_severity",
        "CREATE INDEX index_incident_service_severity IF NOT EXISTS "
        "FOR (i:Incident) ON (i.service_id, i.severity)",
    ),
]


def main() -> int:
    if not NEO4J_PASSWORD:
        print("ERROR: NEO4J_PASSWORD not set", flush=True)
        return 1

    driver: Driver = GraphDatabase.driver(
        NEO4J_URI,
        auth=(NEO4J_USERNAME, NEO4J_PASSWORD),
    )

    try:
        with driver.session(database="neo4j") as session:
            # Log cluster topology — non-fatal if procedure unavailable on Community Edition
            try:
                overview = session.run(
                    "CALL dbms.cluster.overview() YIELD role RETURN role"
                ).data()
                print(f"Cluster overview: {overview}")
            except Exception as exc:  # noqa: BLE001
                print(f"WARNING: Could not read cluster overview ({exc}). Proceeding.")

            print("\nApplying constraints...")
            for name, stmt in CONSTRAINTS:
                session.run(stmt)
                print(f"  [OK] {name}")

            print("\nApplying indexes...")
            for name, stmt in INDEXES:
                session.run(stmt)
                print(f"  [OK] {name}")

            # Verify all expected constraints are present
            constraint_names = {
                r["name"]
                for r in session.run("SHOW CONSTRAINTS YIELD name RETURN name").data()
            }
            missing = [name for name, _ in CONSTRAINTS if name not in constraint_names]
            if missing:
                print(f"ERROR: Missing constraints after creation: {missing}", flush=True)
                return 1

            print(
                f"\n{len(CONSTRAINTS)} constraints and {len(INDEXES)} indexes applied successfully."
            )
    finally:
        driver.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())

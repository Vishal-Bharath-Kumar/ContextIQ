-- 02-init-dbs.sql — Create additional databases required by ContextIQ services.
-- Runs once on first PostgreSQL startup via docker-entrypoint-initdb.d.

-- Keycloak database (Keycloak 24 requires its own schema)
CREATE DATABASE keycloak;
GRANT ALL PRIVILEGES ON DATABASE keycloak TO contextiq;

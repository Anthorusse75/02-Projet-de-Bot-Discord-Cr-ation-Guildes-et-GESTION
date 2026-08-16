DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'did_app') THEN
        CREATE ROLE did_app LOGIN PASSWORD 'local_app_password' NOSUPERUSER NOCREATEDB NOCREATEROLE;
    END IF;
END
$$;

SELECT format('GRANT CONNECT ON DATABASE %I TO did_app', current_database()) \gexec

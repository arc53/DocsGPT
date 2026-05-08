DO $$
DECLARE r record;
BEGIN
  FOR r IN
    SELECT tablename
      FROM pg_tables
     WHERE schemaname='public'
       AND tablename <> 'alembic_version'
  LOOP
    EXECUTE format('TRUNCATE TABLE %I RESTART IDENTITY CASCADE', r.tablename);
  END LOOP;
END $$;

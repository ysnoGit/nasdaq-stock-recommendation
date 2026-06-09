-- Optional manual cleanup only. This file is never executed automatically.
-- It removes only tables whose names begin with backtest_ in the public schema.
DO $$
DECLARE
    table_record record;
BEGIN
    FOR table_record IN
        SELECT tablename
        FROM pg_tables
        WHERE schemaname = 'public'
          AND tablename LIKE 'backtest\_%' ESCAPE '\'
    LOOP
        EXECUTE format('DROP TABLE IF EXISTS public.%I CASCADE', table_record.tablename);
    END LOOP;
END
$$;

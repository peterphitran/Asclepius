ALTER TABLE daemon_control ADD COLUMN execution_available INTEGER NOT NULL DEFAULT 0 CHECK(execution_available IN (0,1));

ALTER TABLE daemon_control ADD COLUMN pid INTEGER CHECK(pid IS NULL OR pid > 0);

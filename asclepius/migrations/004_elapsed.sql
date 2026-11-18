ALTER TABLE daemon_control ADD COLUMN heartbeat_clock TEXT;
ALTER TABLE daemon_control ADD COLUMN heartbeat_tick_ns INTEGER;
ALTER TABLE runs ADD COLUMN started_clock TEXT;
ALTER TABLE runs ADD COLUMN started_tick_ns INTEGER;

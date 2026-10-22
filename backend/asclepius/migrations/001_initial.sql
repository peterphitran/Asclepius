CREATE TABLE profiles (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    config_json TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK(revision > 0),
    deleted_at TEXT
);
CREATE TABLE runs (
    id TEXT PRIMARY KEY,
    profile_id TEXT NOT NULL REFERENCES profiles(id),
    snapshot_json TEXT NOT NULL,
    source_run_id TEXT REFERENCES runs(id),
    state TEXT NOT NULL CHECK(state IN ('queued','running','completed','failed','cancelled','interrupted')),
    owner_id TEXT,
    cancel_requested INTEGER NOT NULL DEFAULT 0 CHECK(cancel_requested IN (0,1)),
    reason TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    CHECK((state = 'running' AND owner_id IS NOT NULL) OR (state <> 'running' AND owner_id IS NULL))
);
CREATE INDEX runs_queue ON runs(state, created_at, id);
CREATE TABLE work_items (
    run_id TEXT NOT NULL REFERENCES runs(id),
    id TEXT NOT NULL,
    check_id TEXT NOT NULL,
    variant_id TEXT,
    variant_json TEXT,
    PRIMARY KEY(run_id, id),
    UNIQUE(run_id, id, variant_id),
    UNIQUE(run_id, variant_id)
);
CREATE TABLE stages (
    run_id TEXT NOT NULL,
    work_item_id TEXT NOT NULL,
    stage TEXT NOT NULL CHECK(stage IN ('selector','generator','judge','reporter')),
    output_json TEXT NOT NULL,
    completed_at TEXT NOT NULL,
    PRIMARY KEY(run_id, work_item_id, stage),
    FOREIGN KEY(run_id, work_item_id) REFERENCES work_items(run_id, id)
);
CREATE TABLE stage_attempts (
    run_id TEXT NOT NULL,
    work_item_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    attempt INTEGER NOT NULL CHECK(attempt > 0),
    state TEXT NOT NULL CHECK(state IN ('pending','completed','failed')),
    started_at TEXT,
    finished_at TEXT,
    error_code TEXT,
    PRIMARY KEY(run_id, work_item_id, stage, attempt),
    FOREIGN KEY(run_id, work_item_id) REFERENCES work_items(run_id, id)
);
CREATE TABLE operations (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    work_item_id TEXT NOT NULL,
    request_json TEXT NOT NULL,
    started_at TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('pending','observed','unknown')),
    UNIQUE(id, run_id, work_item_id),
    FOREIGN KEY(run_id, work_item_id) REFERENCES work_items(run_id, id)
);
CREATE TABLE observations (
    id TEXT PRIMARY KEY,
    operation_id TEXT NOT NULL UNIQUE,
    run_id TEXT NOT NULL,
    work_item_id TEXT NOT NULL,
    document_json TEXT NOT NULL,
    FOREIGN KEY(operation_id, run_id, work_item_id) REFERENCES operations(id, run_id, work_item_id)
);
CREATE TABLE judgments (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    work_item_id TEXT NOT NULL,
    variant_id TEXT NOT NULL,
    document_json TEXT NOT NULL,
    UNIQUE(run_id, variant_id),
    UNIQUE(id, run_id, variant_id),
    FOREIGN KEY(run_id, work_item_id, variant_id) REFERENCES work_items(run_id, id, variant_id)
);
CREATE TABLE findings (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    variant_id TEXT NOT NULL,
    judgment_id TEXT NOT NULL,
    document_json TEXT NOT NULL,
    UNIQUE(run_id, variant_id),
    FOREIGN KEY(judgment_id, run_id, variant_id) REFERENCES judgments(id, run_id, variant_id)
);
CREATE TABLE events (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(id),
    kind TEXT NOT NULL,
    data_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX events_run ON events(run_id, sequence);
CREATE TABLE daemon_control (
    singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
    instance_id TEXT,
    state TEXT NOT NULL CHECK(state IN ('stopped','starting','ready','draining')),
    heartbeat_at TEXT
);
INSERT INTO daemon_control(singleton, state) VALUES(1, 'stopped');
CREATE TABLE budget_reservations (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id),
    kind TEXT NOT NULL CHECK(kind IN ('target','evaluator','cleanup')),
    max_output INTEGER NOT NULL CHECK(max_output > 0),
    state TEXT NOT NULL CHECK(state IN ('reserved','dispatched','settled','released'))
);

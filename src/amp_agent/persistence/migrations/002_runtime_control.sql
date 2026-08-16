CREATE TABLE IF NOT EXISTS amp.workspaces (
    id UUID PRIMARY KEY,
    workspace_key TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO amp.workspaces(id, workspace_key, name)
VALUES ('00000000-0000-0000-0000-000000000001', 'local', 'Local')
ON CONFLICT (workspace_key) DO NOTHING;

ALTER TABLE amp.conversations ADD COLUMN IF NOT EXISTS workspace_id UUID;
UPDATE amp.conversations SET workspace_id = '00000000-0000-0000-0000-000000000001' WHERE workspace_id IS NULL;
ALTER TABLE amp.conversations ALTER COLUMN workspace_id SET NOT NULL;
ALTER TABLE amp.conversations ADD CONSTRAINT conversations_workspace_fk
    FOREIGN KEY (workspace_id) REFERENCES amp.workspaces(id);

CREATE TABLE IF NOT EXISTS amp.agent_versions (
    id UUID PRIMARY KEY,
    agent_id UUID NOT NULL REFERENCES amp.agents(id),
    version TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (agent_id, version)
);

INSERT INTO amp.agent_versions(id, agent_id, version)
SELECT gen_random_uuid(), id, version FROM amp.agents
ON CONFLICT (agent_id, version) DO NOTHING;

ALTER TABLE amp.executions ADD COLUMN IF NOT EXISTS workspace_id UUID;
ALTER TABLE amp.executions ADD COLUMN IF NOT EXISTS agent_id UUID;
ALTER TABLE amp.executions ADD COLUMN IF NOT EXISTS agent_version_id UUID;
ALTER TABLE amp.executions ADD COLUMN IF NOT EXISTS root_execution_id UUID;
ALTER TABLE amp.executions ADD COLUMN IF NOT EXISTS parent_execution_id UUID;
ALTER TABLE amp.executions ADD COLUMN IF NOT EXISTS trigger_kind TEXT;
ALTER TABLE amp.executions ADD COLUMN IF NOT EXISTS trigger_id TEXT;
ALTER TABLE amp.executions ADD COLUMN IF NOT EXISTS checkpoint_thread_id UUID;
ALTER TABLE amp.executions ADD COLUMN IF NOT EXISTS root_span_id UUID;
ALTER TABLE amp.executions ADD COLUMN IF NOT EXISTS requested_deadline_at TIMESTAMPTZ;
ALTER TABLE amp.executions ADD COLUMN IF NOT EXISTS effective_deadline_at TIMESTAMPTZ;
ALTER TABLE amp.executions ADD COLUMN IF NOT EXISTS limit_policy_version TEXT;
ALTER TABLE amp.executions ADD COLUMN IF NOT EXISTS retry_policy_version TEXT;
ALTER TABLE amp.executions ADD COLUMN IF NOT EXISTS history_policy_version TEXT;
ALTER TABLE amp.executions ADD COLUMN IF NOT EXISTS max_steps INTEGER;
ALTER TABLE amp.executions ADD COLUMN IF NOT EXISTS used_steps INTEGER NOT NULL DEFAULT 0;
ALTER TABLE amp.executions ADD COLUMN IF NOT EXISTS max_tool_calls INTEGER;
ALTER TABLE amp.executions ADD COLUMN IF NOT EXISTS used_tool_calls INTEGER NOT NULL DEFAULT 0;
ALTER TABLE amp.executions ADD COLUMN IF NOT EXISTS model_timeout_seconds INTEGER;
ALTER TABLE amp.executions ADD COLUMN IF NOT EXISTS tool_timeout_seconds INTEGER;
ALTER TABLE amp.executions ADD COLUMN IF NOT EXISTS history_max_messages INTEGER;
ALTER TABLE amp.executions ADD COLUMN IF NOT EXISTS history_max_estimated_tokens INTEGER;
ALTER TABLE amp.executions ADD COLUMN IF NOT EXISTS history_used_messages INTEGER;
ALTER TABLE amp.executions ADD COLUMN IF NOT EXISTS history_estimated_tokens INTEGER;
ALTER TABLE amp.executions ADD COLUMN IF NOT EXISTS next_event_sequence BIGINT NOT NULL DEFAULT 1;
ALTER TABLE amp.executions ADD COLUMN IF NOT EXISTS cancel_requested_at TIMESTAMPTZ;
ALTER TABLE amp.executions ADD COLUMN IF NOT EXISTS cancel_effective_at TIMESTAMPTZ;
ALTER TABLE amp.executions ADD COLUMN IF NOT EXISTS cancel_reason TEXT;
ALTER TABLE amp.executions ADD COLUMN IF NOT EXISTS cancel_requested_by JSONB;
ALTER TABLE amp.executions ADD COLUMN IF NOT EXISTS error_fingerprint TEXT;
ALTER TABLE amp.executions ADD COLUMN IF NOT EXISTS error_retryable BOOLEAN;
ALTER TABLE amp.executions ADD COLUMN IF NOT EXISTS timeline_complete BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE amp.executions ADD COLUMN IF NOT EXISTS timeline_pruned_through BIGINT;

UPDATE amp.executions e
SET workspace_id = c.workspace_id,
    agent_id = c.agent_id,
    root_execution_id = e.id,
    trigger_kind = 'inbound_request',
    trigger_id = e.inbound_request_id::text,
    checkpoint_thread_id = COALESCE(e.checkpoint_thread_id, gen_random_uuid()),
    root_span_id = COALESCE(e.root_span_id, gen_random_uuid()),
    requested_deadline_at = (SELECT r.deadline_at FROM amp.inbound_requests r WHERE r.execution_id = e.id),
    effective_deadline_at = COALESCE((SELECT r.deadline_at FROM amp.inbound_requests r WHERE r.execution_id = e.id), e.created_at + interval '120 seconds'),
    limit_policy_version = COALESCE(e.limit_policy_version, 'runtime-v1'),
    retry_policy_version = COALESCE(e.retry_policy_version, 'retry-v1'),
    history_policy_version = COALESCE(e.history_policy_version, 'recent-v1'),
    max_steps = COALESCE(e.max_steps, 12),
    max_tool_calls = COALESCE(e.max_tool_calls, 4),
    model_timeout_seconds = COALESCE(e.model_timeout_seconds, 45),
    tool_timeout_seconds = COALESCE(e.tool_timeout_seconds, 10)
FROM amp.conversations c
WHERE c.id = e.conversation_id;

INSERT INTO amp.agent_versions(id, agent_id, version)
SELECT gen_random_uuid(), e.agent_id, e.agent_version
FROM amp.executions e
WHERE e.agent_id IS NOT NULL
ON CONFLICT (agent_id, version) DO NOTHING;

UPDATE amp.executions e
SET agent_version_id = v.id
FROM amp.agent_versions v
WHERE v.agent_id = e.agent_id AND v.version = e.agent_version;

ALTER TABLE amp.executions ALTER COLUMN workspace_id SET NOT NULL;
ALTER TABLE amp.executions ALTER COLUMN agent_id SET NOT NULL;
ALTER TABLE amp.executions ALTER COLUMN root_execution_id SET NOT NULL;
ALTER TABLE amp.executions ALTER COLUMN trigger_kind SET NOT NULL;
ALTER TABLE amp.executions ALTER COLUMN checkpoint_thread_id SET NOT NULL;
ALTER TABLE amp.executions ALTER COLUMN root_span_id SET NOT NULL;
ALTER TABLE amp.executions ALTER COLUMN max_steps SET NOT NULL;
ALTER TABLE amp.executions ALTER COLUMN max_tool_calls SET NOT NULL;
ALTER TABLE amp.executions ALTER COLUMN model_timeout_seconds SET NOT NULL;
ALTER TABLE amp.executions ALTER COLUMN tool_timeout_seconds SET NOT NULL;

ALTER TABLE amp.executions ADD CONSTRAINT executions_workspace_fk FOREIGN KEY (workspace_id) REFERENCES amp.workspaces(id);
ALTER TABLE amp.executions ADD CONSTRAINT executions_agent_fk FOREIGN KEY (agent_id) REFERENCES amp.agents(id);
ALTER TABLE amp.executions ADD CONSTRAINT executions_agent_version_fk FOREIGN KEY (agent_version_id) REFERENCES amp.agent_versions(id);
ALTER TABLE amp.executions ADD CONSTRAINT executions_root_fk FOREIGN KEY (root_execution_id) REFERENCES amp.executions(id);

ALTER TABLE amp.execution_events ADD COLUMN IF NOT EXISTS workspace_id UUID;
ALTER TABLE amp.execution_events ADD COLUMN IF NOT EXISTS sequence_no BIGINT;
ALTER TABLE amp.execution_events ADD COLUMN IF NOT EXISTS event_name TEXT;
ALTER TABLE amp.execution_events ADD COLUMN IF NOT EXISTS schema_version INTEGER NOT NULL DEFAULT 1;
ALTER TABLE amp.execution_events ADD COLUMN IF NOT EXISTS category TEXT NOT NULL DEFAULT 'diagnostic';
ALTER TABLE amp.execution_events ADD COLUMN IF NOT EXISTS occurred_at TIMESTAMPTZ;
ALTER TABLE amp.execution_events ADD COLUMN IF NOT EXISTS recorded_at TIMESTAMPTZ;
ALTER TABLE amp.execution_events ADD COLUMN IF NOT EXISTS attempt_no INTEGER;
ALTER TABLE amp.execution_events ADD COLUMN IF NOT EXISTS span_id UUID;
ALTER TABLE amp.execution_events ADD COLUMN IF NOT EXISTS parent_span_id UUID;
ALTER TABLE amp.execution_events ADD COLUMN IF NOT EXISTS causation_event_id UUID;
ALTER TABLE amp.execution_events ADD COLUMN IF NOT EXISTS duration_ms DOUBLE PRECISION;
ALTER TABLE amp.execution_events ADD COLUMN IF NOT EXISTS outcome TEXT;
ALTER TABLE amp.execution_events ADD COLUMN IF NOT EXISTS error_code TEXT;
ALTER TABLE amp.execution_events ADD COLUMN IF NOT EXISTS is_retryable BOOLEAN;
ALTER TABLE amp.execution_events ADD COLUMN IF NOT EXISTS error_fingerprint TEXT;
ALTER TABLE amp.execution_events ADD COLUMN IF NOT EXISTS input_tokens INTEGER;
ALTER TABLE amp.execution_events ADD COLUMN IF NOT EXISTS output_tokens INTEGER;
ALTER TABLE amp.execution_events ADD COLUMN IF NOT EXISTS tool_name TEXT;
ALTER TABLE amp.execution_events ADD COLUMN IF NOT EXISTS model_name TEXT;

WITH numbered AS (
    SELECT id, row_number() OVER (PARTITION BY execution_id ORDER BY created_at, id)::BIGINT AS n
    FROM amp.execution_events
)
UPDATE amp.execution_events e SET sequence_no = n.n
FROM numbered n WHERE n.id = e.id;

UPDATE amp.execution_events e
SET workspace_id = x.workspace_id,
    event_name = CASE e.event_type
        WHEN 'execution.completed' THEN 'execution.succeeded'
        WHEN 'job.retried' THEN 'job.retry_scheduled'
        ELSE e.event_type
    END,
    occurred_at = COALESCE(e.occurred_at, e.created_at),
    recorded_at = COALESCE(e.recorded_at, e.created_at),
    category = CASE
        WHEN e.event_type LIKE 'execution.%' OR e.event_type LIKE 'job.%' THEN 'lifecycle'
        ELSE 'diagnostic'
    END
FROM amp.executions x WHERE x.id = e.execution_id;

ALTER TABLE amp.execution_events ALTER COLUMN workspace_id SET NOT NULL;
ALTER TABLE amp.execution_events ALTER COLUMN sequence_no SET NOT NULL;
ALTER TABLE amp.execution_events ALTER COLUMN event_name SET NOT NULL;
ALTER TABLE amp.execution_events ALTER COLUMN occurred_at SET NOT NULL;
ALTER TABLE amp.execution_events ALTER COLUMN recorded_at SET NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS execution_events_sequence_uidx ON amp.execution_events(execution_id, sequence_no);
CREATE INDEX IF NOT EXISTS execution_events_workspace_time_idx ON amp.execution_events(workspace_id, recorded_at, id);

UPDATE amp.executions e
SET next_event_sequence = COALESCE((SELECT max(sequence_no) + 1 FROM amp.execution_events x WHERE x.execution_id = e.id), 1);

CREATE TABLE IF NOT EXISTS amp.worker_instances (
    worker_id TEXT PRIMARY KEY,
    boot_id UUID NOT NULL,
    service_version TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    state TEXT NOT NULL DEFAULT 'idle',
    current_job_id UUID,
    capabilities JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS executions_workspace_time_idx ON amp.executions(workspace_id, created_at DESC, id DESC);

DO $$
DECLARE c RECORD;
BEGIN
  FOR c IN SELECT conname FROM pg_constraint WHERE conrelid = 'amp.executions'::regclass AND contype = 'c' AND conname LIKE '%status%'
  LOOP EXECUTE format('ALTER TABLE amp.executions DROP CONSTRAINT %I', c.conname); END LOOP;
  FOR c IN SELECT conname FROM pg_constraint WHERE conrelid = 'amp.jobs'::regclass AND contype = 'c' AND conname LIKE '%status%'
  LOOP EXECUTE format('ALTER TABLE amp.jobs DROP CONSTRAINT %I', c.conname); END LOOP;
END $$;

ALTER TABLE amp.executions ADD CONSTRAINT executions_status_check
    CHECK (status IN ('queued', 'running', 'waiting_approval', 'succeeded', 'failed', 'cancelled'));
ALTER TABLE amp.jobs ADD CONSTRAINT jobs_status_check
    CHECK (status IN ('queued', 'running', 'retry', 'waiting_approval', 'succeeded', 'dead', 'cancelled'));

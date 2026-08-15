CREATE SCHEMA IF NOT EXISTS amp;
CREATE SCHEMA IF NOT EXISTS langgraph;

CREATE TABLE IF NOT EXISTS amp.schema_migrations (
    version TEXT PRIMARY KEY,
    checksum TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS amp.agents (
    id UUID PRIMARY KEY,
    agent_key TEXT NOT NULL UNIQUE,
    version TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS amp.conversations (
    id UUID PRIMARY KEY,
    agent_id UUID NOT NULL REFERENCES amp.agents(id),
    channel TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'closed')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    closed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS amp.inbound_requests (
    id UUID PRIMARY KEY,
    source TEXT NOT NULL,
    request_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    conversation_id UUID NOT NULL REFERENCES amp.conversations(id),
    execution_id UUID,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    reply_channel TEXT,
    deadline_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source, request_id),
    UNIQUE (source, idempotency_key)
);

CREATE TABLE IF NOT EXISTS amp.executions (
    id UUID PRIMARY KEY,
    conversation_id UUID NOT NULL REFERENCES amp.conversations(id),
    inbound_request_id UUID REFERENCES amp.inbound_requests(id),
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')),
    result TEXT,
    error_code TEXT,
    error_message TEXT,
    agent_key TEXT NOT NULL,
    agent_version TEXT NOT NULL,
    graph_version TEXT NOT NULL,
    state_version INTEGER NOT NULL,
    model_profile TEXT,
    reply_channel TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS amp.messages (
    id UUID PRIMARY KEY,
    conversation_id UUID NOT NULL REFERENCES amp.conversations(id),
    execution_id UUID REFERENCES amp.executions(id),
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'tool', 'system')),
    content TEXT NOT NULL,
    sequence_no BIGINT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (conversation_id, sequence_no)
);

CREATE TABLE IF NOT EXISTS amp.jobs (
    id UUID PRIMARY KEY,
    execution_id UUID NOT NULL UNIQUE REFERENCES amp.executions(id),
    conversation_id UUID NOT NULL REFERENCES amp.conversations(id),
    dedupe_key TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'running', 'retry', 'succeeded', 'dead', 'cancelled')),
    priority INTEGER NOT NULL DEFAULT 0,
    available_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    lease_owner TEXT,
    lease_token UUID,
    lease_expires_at TIMESTAMPTZ,
    heartbeat_at TIMESTAMPTZ,
    last_error_code TEXT,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS amp.execution_events (
    id UUID PRIMARY KEY,
    execution_id UUID NOT NULL REFERENCES amp.executions(id),
    event_type TEXT NOT NULL,
    node_name TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS amp.outbox_events (
    id UUID PRIMARY KEY,
    execution_id UUID NOT NULL REFERENCES amp.executions(id),
    event_type TEXT NOT NULL,
    reply_channel TEXT NOT NULL,
    payload JSONB NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'published', 'retry', 'dead')),
    attempts INTEGER NOT NULL DEFAULT 0,
    available_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    published_at TIMESTAMPTZ,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (execution_id, event_type)
);

CREATE UNIQUE INDEX IF NOT EXISTS executions_one_running_per_conversation
    ON amp.executions (conversation_id)
    WHERE status = 'running';

CREATE UNIQUE INDEX IF NOT EXISTS messages_one_assistant_per_execution
    ON amp.messages (execution_id)
    WHERE role = 'assistant';

CREATE INDEX IF NOT EXISTS jobs_claim_idx
    ON amp.jobs (priority DESC, available_at, created_at)
    WHERE status IN ('queued', 'retry');

CREATE INDEX IF NOT EXISTS messages_conversation_idx
    ON amp.messages (conversation_id, sequence_no);

CREATE INDEX IF NOT EXISTS execution_events_execution_idx
    ON amp.execution_events (execution_id, created_at);

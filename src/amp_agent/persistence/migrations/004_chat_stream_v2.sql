-- Durable Agent Streaming Protocol projection.  This is deliberately
-- independent from amp.execution_events, which remains an observability log.
ALTER TABLE amp.conversations
    ADD COLUMN IF NOT EXISTS stream_protocol_version INTEGER NOT NULL DEFAULT 2;

-- Existing prototype threads are retained for audit but excluded from the v2 UI.
UPDATE amp.conversations
SET stream_protocol_version = 1,
    archived_at = COALESCE(archived_at, now())
WHERE stream_protocol_version = 2
  AND created_at < now();

CREATE TABLE IF NOT EXISTS amp.thread_stream_events (
    seq BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    thread_id UUID NOT NULL REFERENCES amp.conversations(id),
    run_id UUID NOT NULL REFERENCES amp.executions(id),
    event_key TEXT NOT NULL,
    protocol_version INTEGER NOT NULL DEFAULT 2,
    method TEXT NOT NULL,
    namespace JSONB NOT NULL DEFAULT '[]'::jsonb,
    params JSONB NOT NULL DEFAULT '{}'::jsonb,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (run_id, event_key)
);

CREATE INDEX IF NOT EXISTS thread_stream_events_thread_seq_idx
    ON amp.thread_stream_events(thread_id, seq);
CREATE INDEX IF NOT EXISTS thread_stream_events_run_seq_idx
    ON amp.thread_stream_events(run_id, seq);

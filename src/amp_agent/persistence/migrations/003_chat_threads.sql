ALTER TABLE amp.conversations ADD COLUMN IF NOT EXISTS title TEXT;
ALTER TABLE amp.conversations ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ;
ALTER TABLE amp.conversations ADD COLUMN IF NOT EXISTS last_message_at TIMESTAMPTZ;

UPDATE amp.conversations
SET title = COALESCE(NULLIF(title, ''), 'Nova conversa'),
    last_message_at = COALESCE(last_message_at, updated_at)
WHERE title IS NULL OR last_message_at IS NULL;

ALTER TABLE amp.conversations ALTER COLUMN title SET DEFAULT 'Nova conversa';
ALTER TABLE amp.conversations ALTER COLUMN title SET NOT NULL;
ALTER TABLE amp.conversations ALTER COLUMN last_message_at SET DEFAULT now();
ALTER TABLE amp.conversations ALTER COLUMN last_message_at SET NOT NULL;
CREATE INDEX IF NOT EXISTS conversations_workspace_activity_idx
    ON amp.conversations(workspace_id, archived_at, last_message_at DESC, id DESC);

CREATE TABLE IF NOT EXISTS amp.approval_decisions (
    execution_id UUID NOT NULL REFERENCES amp.executions(id),
    tool_call_id TEXT NOT NULL,
    decision JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (execution_id, tool_call_id)
);

CREATE TABLE IF NOT EXISTS amp.notes (
    workspace_id UUID NOT NULL REFERENCES amp.workspaces(id),
    note_key TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (workspace_id, note_key)
);

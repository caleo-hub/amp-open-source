'use client';

import { HttpAgentServerAdapter } from '@langchain/react';

/** The browser only speaks to the authenticated Next.js BFF. */
export function createAmpTransport(threadId: string) {
  return new HttpAgentServerAdapter({
    apiUrl: '/api',
    threadId,
    paths: {
      commands: `/threads/${threadId}/commands`,
      stream: `/threads/${threadId}/stream`,
      state: `/threads/${threadId}/state`,
    },
  });
}

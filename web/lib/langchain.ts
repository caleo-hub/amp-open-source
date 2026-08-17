/* The UI-specific transport stays in page.tsx so the BFF can carry SSE.
 * This type bridge keeps the protocol adapter aligned with @langchain/react's
 * public stream shape without coupling the browser to the internal API token. */
import type { UseStreamReturn } from '@langchain/react';

export type AmpLangChainStream = UseStreamReturn<Record<string, unknown>>;

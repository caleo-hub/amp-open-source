import {
  CopilotRuntime,
  ExperimentalEmptyAdapter,
  copilotRuntimeNextJSAppRouterEndpoint,
} from '@copilotkit/runtime';
import { HttpAgent } from '@ag-ui/client';
import { cookies } from 'next/headers';
import { NextRequest, NextResponse } from 'next/server';
import crypto from 'node:crypto';

const sessionName = 'amp_chat_session';

function validSession(value: string | undefined) {
  const secret = process.env.AMP_CHAT_SESSION_SECRET || process.env.AMP_CHAT_TOKEN || 'local-development-secret';
  const expected = crypto.createHmac('sha256', secret).update(process.env.AMP_CHAT_TOKEN || '').digest('hex');
  return !!value && value.length === expected.length && crypto.timingSafeEqual(Buffer.from(value), Buffer.from(expected));
}

const runtime = new CopilotRuntime({
  agents: {
    amp: new HttpAgent({ url: `${process.env.AMP_API_URL || 'http://127.0.0.1:8000'}/ag-ui` }),
  },
});
const serviceAdapter = new ExperimentalEmptyAdapter();

async function handle(request: NextRequest) {
  if (!validSession((await cookies()).get(sessionName)?.value)) {
    return NextResponse.json({ error: 'unauthorized' }, { status: 401 });
  }
  const configuredOrigin = process.env.AMP_PUBLIC_ORIGIN;
  if (request.method !== 'GET' && configuredOrigin && request.headers.get('origin') !== configuredOrigin) {
    return NextResponse.json({ error: 'invalid_origin' }, { status: 403 });
  }
  const { handleRequest } = copilotRuntimeNextJSAppRouterEndpoint({
    runtime,
    serviceAdapter,
    endpoint: '/api/copilotkit',
  });
  return handleRequest(request);
}

export const GET = handle;
export const POST = handle;

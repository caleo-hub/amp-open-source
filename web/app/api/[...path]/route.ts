import { cookies } from 'next/headers';
import { NextResponse } from 'next/server';
import crypto from 'node:crypto';
const name = 'amp_chat_session';
function ok(value: string | undefined) { const secret = process.env.AMP_CHAT_SESSION_SECRET || process.env.AMP_CHAT_TOKEN || 'local-development-secret'; const expected = crypto.createHmac('sha256', secret).update(process.env.AMP_CHAT_TOKEN || '').digest('hex'); return !!value && value.length === expected.length && crypto.timingSafeEqual(Buffer.from(value), Buffer.from(expected)); }
async function proxy(request: Request, context: { params: Promise<{ path: string[] }> }) {
  if (!ok((await cookies()).get(name)?.value)) return NextResponse.json({ error: 'unauthorized' }, { status: 401 });
  const configuredOrigin = process.env.AMP_PUBLIC_ORIGIN;
  if (!['GET', 'HEAD'].includes(request.method) && configuredOrigin && request.headers.get('origin') !== configuredOrigin) return NextResponse.json({ error: 'invalid_origin' }, { status: 403 });
  const { path } = await context.params;
  const target = `${process.env.AMP_API_URL || 'http://127.0.0.1:8000'}/${path.join('/')}${new URL(request.url).search}`;
  const headers = new Headers(request.headers); headers.delete('host'); headers.delete('accept-encoding'); headers.set('X-AMP-Chat-Token', process.env.AMP_CHAT_TOKEN || '');
  const init: RequestInit & { duplex?: 'half' } = { method: request.method, headers, body: ['GET', 'HEAD'].includes(request.method) ? undefined : request.body, duplex: 'half', cache: 'no-store' };
  const response = await fetch(target, init); const output = new Headers(response.headers); output.delete('content-encoding'); output.set('Cache-Control', 'no-cache, no-transform'); output.set('X-Accel-Buffering', 'no');
  return new NextResponse(response.body, { status: response.status, headers: output });
}
export const GET = proxy; export const POST = proxy; export const PATCH = proxy; export const DELETE = proxy;

import { cookies } from 'next/headers';
import { NextResponse } from 'next/server';
import crypto from 'node:crypto';
const name = 'amp_chat_session';
const secret = () => process.env.AMP_CHAT_SESSION_SECRET || process.env.AMP_CHAT_TOKEN || 'local-development-secret';
const digest = (value: string) => crypto.createHmac('sha256', secret()).update(value).digest('hex');
const equal = (a: string, b: string) => a.length === b.length && crypto.timingSafeEqual(Buffer.from(a), Buffer.from(b));
export async function GET() { return equal((await cookies()).get(name)?.value || '', digest(process.env.AMP_CHAT_TOKEN || '')) ? NextResponse.json({ authenticated: true }) : NextResponse.json({ authenticated: false }, { status: 401 }); }
export async function POST(request: Request) { const supplied = String((await request.json().catch(() => ({}))).token || ''); const configured = process.env.AMP_CHAT_TOKEN || ''; if (!configured || !equal(supplied, configured)) return NextResponse.json({ error: 'invalid_token' }, { status: 401 }); const response = NextResponse.json({ authenticated: true }); response.cookies.set(name, digest(supplied), { httpOnly: true, sameSite: 'strict', secure: process.env.AMP_PUBLIC_ORIGIN?.startsWith('https://') || false, path: '/', maxAge: 43200 }); return response; }

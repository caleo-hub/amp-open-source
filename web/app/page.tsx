'use client';

import { FormEvent, useEffect, useState } from 'react';
import { CopilotChat, CopilotKit } from '@copilotkit/react-core/v2';

type Thread = { thread_id: string; title: string; archived_at?: string | null; last_message_at?: string };
type Run = { run_id: string; status: string; created_at?: string };
type Checkpoint = { checkpoint_id?: string; parent_checkpoint_id?: string; created_at?: string; next?: string[]; metadata?: Record<string, unknown> };

async function api(path: string, init?: RequestInit) {
  const headers = new Headers(init?.headers);
  if (init?.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
  const response = await fetch(`/api${path}`, { ...init, headers, cache: 'no-store' });
  if (!response.ok) throw new Error(response.status === 401 ? 'auth' : await response.text());
  return response;
}

function ThreadChat({ thread, onRefresh }: { thread: Thread; onRefresh: () => Promise<void> }) {
  return <CopilotKit key={thread.thread_id} runtimeUrl="/api/copilotkit" agent="amp" credentials="same-origin" useSingleEndpoint>
    <section className="chat copilot-chat"><header><div><span className="eyebrow">THREAD</span><h2>{thread.title || 'Nova conversa'}</h2></div><span className="status">AG-UI · CopilotKit</span></header>
      <div className="copilot-surface"><CopilotChat agentId="amp" threadId={thread.thread_id} labels={{ chatInputPlaceholder: 'Escreva uma mensagem…', welcomeMessageText: 'Como posso ajudar?', chatDisclaimerText: 'As respostas podem conter imprecisões.' }} /></div>
    </section>
    <RuntimeInspector thread={thread} onRefresh={onRefresh} />
  </CopilotKit>;
}

function RuntimeInspector({ thread, onRefresh }: { thread: Thread; onRefresh: () => Promise<void> }) {
  const [runs, setRuns] = useState<Run[]>([]);
  const [checkpoints, setCheckpoints] = useState<Checkpoint[]>([]);
  const [selectedCheckpoint, setSelectedCheckpoint] = useState<Checkpoint | null>(null);
  const [error, setError] = useState('');
  const refresh = async () => {
    try {
      const [runsResponse, historyResponse] = await Promise.all([api(`/threads/${thread.thread_id}/runs`), api(`/threads/${thread.thread_id}/history?limit=30`)]);
      const nextRuns = ((await runsResponse.json()).runs || []) as Run[];
      const nextCheckpoints = ((await historyResponse.json()).checkpoints || []) as Checkpoint[];
      setRuns(nextRuns); setCheckpoints(nextCheckpoints); setSelectedCheckpoint((old) => old || nextCheckpoints[0] || null);
      await onRefresh();
    } catch { setError('Não foi possível atualizar a execução.'); }
  };
  useEffect(() => { void refresh(); const timer = window.setInterval(() => void refresh(), 2500); return () => window.clearInterval(timer); }, [thread.thread_id]);
  async function cancel(run: Run) { try { await api(`/threads/${thread.thread_id}/runs/${run.run_id}/cancel`, { method: 'POST', body: '{}' }); await refresh(); } catch { setError('Falha ao cancelar a execução.'); } }
  async function retry(run: Run) { try { await api(`/threads/${thread.thread_id}/runs/${run.run_id}/retry`, { method: 'POST', body: '{}' }); await refresh(); } catch { setError('Falha ao repetir a execução.'); } }
  async function decide(response: unknown) {
    try { await api(`/threads/${thread.thread_id}/commands`, { method: 'POST', body: JSON.stringify({ method: 'input.respond', params: { response } }) }); await refresh(); }
    catch { setError('Não foi possível registrar a decisão.'); }
  }
  return <aside className="inspector"><span className="eyebrow">RUNTIME</span><b>Runs</b>{runs.slice(0, 6).map((run) => <div className="run-card" key={run.run_id}><span>{run.status}</span><small>{run.created_at && new Date(run.created_at).toLocaleTimeString('pt-BR')}</small>{['queued', 'running'].includes(run.status) && <button className="outline" onClick={() => void cancel(run)}>Cancelar</button>}{['completed', 'failed', 'cancelled'].includes(run.status) && <button className="outline" onClick={() => void retry(run)}>Repetir</button>}{run.status === 'interrupted' && <div className="approval-actions"><button className="outline" onClick={() => void decide(false)}>Rejeitar</button><button className="primary" onClick={() => void decide(true)}>Aprovar</button></div>}</div>)}
    <b className="panel-title">Timeline</b><div className="event"><i /><span>{runs[0]?.status || 'Aguardando execução'}<small>Lifecycle durável</small></span></div>
    <b className="panel-title">Checkpoints</b>{checkpoints.slice(0, 8).map((checkpoint, index) => <button className="checkpoint" key={checkpoint.checkpoint_id || index} onClick={() => setSelectedCheckpoint(checkpoint)}>{checkpoint.checkpoint_id?.slice(0, 14) || `checkpoint ${index + 1}`}<small>{checkpoint.created_at && new Date(checkpoint.created_at).toLocaleString('pt-BR')}</small></button>)}
    {selectedCheckpoint && <pre className="checkpoint-view">{JSON.stringify({ checkpoint_id: selectedCheckpoint.checkpoint_id, parent: selectedCheckpoint.parent_checkpoint_id, next: selectedCheckpoint.next, metadata: selectedCheckpoint.metadata }, null, 2)}</pre>}{error && <p className="error">{error}</p>}
  </aside>;
}

export default function Home() {
  const [authenticated, setAuthenticated] = useState<boolean | null>(null);
  const [token, setToken] = useState(''); const [threads, setThreads] = useState<Thread[]>([]);
  const [selected, setSelected] = useState<Thread | null>(null); const [showArchived, setShowArchived] = useState(false); const [error, setError] = useState('');
  const refreshThreads = async () => {
    try { setThreads(((await (await api(`/threads?include_archived=${showArchived}`)).json()).threads || []) as Thread[]); }
    catch (cause) { if ((cause as Error).message === 'auth') setAuthenticated(false); else setError('Falha ao carregar threads.'); }
  };
  useEffect(() => { api('/session').then(() => setAuthenticated(true)).catch(() => setAuthenticated(false)); }, []);
  useEffect(() => { if (authenticated) void refreshThreads(); }, [authenticated, showArchived]);
  async function login(event: FormEvent) { event.preventDefault(); try { await api('/session', { method: 'POST', body: JSON.stringify({ token }) }); setToken(''); setAuthenticated(true); } catch { setError('Token inválido.'); } }
  async function createThread() { try { const thread = await (await api('/threads', { method: 'POST', body: '{}' })).json() as Thread; await refreshThreads(); setSelected(thread); } catch { setError('Falha ao criar thread.'); } }
  async function rename() { if (!selected) return; const title = window.prompt('Novo título', selected.title); if (!title?.trim()) return; const updated = await (await api(`/threads/${selected.thread_id}`, { method: 'PATCH', body: JSON.stringify({ title }) })).json() as Thread; setSelected(updated); await refreshThreads(); }
  async function archive() { if (!selected) return; await api(`/threads/${selected.thread_id}`, { method: 'PATCH', body: JSON.stringify({ archived: !selected.archived_at }) }); setSelected(null); await refreshThreads(); }
  if (authenticated === null) return <main className="center">Carregando AMP Chat…</main>;
  if (!authenticated) return <main className="center"><form className="login" onSubmit={login}><span className="eyebrow">AMP CHAT</span><h1>Runtime local</h1><p>Informe o token compartilhado da rede local.</p><input autoFocus type="password" value={token} onChange={(event) => setToken(event.target.value)} placeholder="Token de acesso" /><button>Entrar</button>{error && <small className="error">{error}</small>}</form></main>;
  return <main className="shell"><aside className="sidebar"><div className="brand"><b>AMP</b><span>Chat local</span></div><button className="primary" onClick={() => void createThread()}>＋ Nova thread</button><div className="filter"><button className={!showArchived ? 'outline active-filter' : 'outline'} onClick={() => setShowArchived(false)}>Ativas</button><button className={showArchived ? 'outline active-filter' : 'outline'} onClick={() => setShowArchived(true)}>Arquivadas</button></div><div className="threads">{threads.map((thread) => <button className={selected?.thread_id === thread.thread_id ? 'thread active' : 'thread'} key={thread.thread_id} onClick={() => setSelected(thread)}>{thread.title || 'Nova conversa'}<small>{thread.last_message_at && new Date(thread.last_message_at).toLocaleDateString('pt-BR')}</small></button>)}</div></aside>
    {selected ? <ThreadChat key={selected.thread_id} thread={selected} onRefresh={refreshThreads} /> : <section className="chat"><header><div><span className="eyebrow">AMP CHAT</span><h2>Converse com o Ollama</h2></div></header><div className="empty"><h1>Chat durável e observável</h1><p>Crie ou escolha uma thread para começar.</p></div></section>}
    {selected && <div className="thread-actions"><button className="outline" onClick={() => void rename()}>Renomear</button><button className="outline" onClick={() => void archive()}>{selected.archived_at ? 'Restaurar' : 'Arquivar'}</button></div>}{error && <p className="toast error">{error}</p>}
  </main>;
}

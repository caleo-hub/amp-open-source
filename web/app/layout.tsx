import './globals.css';
import 'katex/dist/katex.min.css';
import '@copilotkit/react-core/v2/styles.css';
import type { ReactNode } from 'react';
export const metadata = { title: 'AMP Chat', description: 'Chat local com runtime LangGraph' };
export default function Layout({ children }: { children: ReactNode }) { return <html lang="pt-BR"><body>{children}</body></html>; }

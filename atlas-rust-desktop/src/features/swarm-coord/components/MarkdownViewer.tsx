import { useState } from 'react';
import { Check, Copy, Download } from 'lucide-react';
import { InlineText } from './InlineText';

interface MarkdownViewerProps {
  filePath: string;
  content: string;
  mode: 'formatted' | 'raw';
}

export function MarkdownViewer({ filePath, content, mode }: MarkdownViewerProps) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(content);
      }
    } catch {
      // Clipboard fallback
    }
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1800);
  };

  const handleDownload = () => {
    const fileName = filePath.split('/').pop() || 'skill.md';
    const blob = new Blob([content], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = fileName;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  const lines = content.replace(/^---\n[\s\S]*?\n---\n?/, '').split('\n');

  return (
    <section className="rounded-xl border border-[#232836] bg-[#111622] overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#232836] bg-[#0D121E] px-5 py-3">
        <span className="font-mono text-xs text-slate-300">{filePath}</span>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={handleCopy}
            className="inline-flex items-center gap-1.5 rounded-md border border-[#2A3347] bg-[#171E2F] px-3 py-1.5 text-xs font-medium text-slate-200 hover:border-slate-500 hover:text-white whitespace-nowrap shrink-0 focus-visible:outline-2 focus-visible:outline-blue-500"
          >
            {copied ? (
              <>
                <Check className="h-3.5 w-3.5 text-emerald-400" aria-hidden="true" />
                Copied File
              </>
            ) : (
              <>
                <Copy className="h-3.5 w-3.5" aria-hidden="true" />
                Copy Markdown
              </>
            )}
          </button>
          <button
            type="button"
            onClick={handleDownload}
            className="inline-flex items-center gap-1.5 rounded-md border border-[#2A3347] bg-[#171E2F] px-3 py-1.5 text-xs font-medium text-slate-200 hover:border-slate-500 hover:text-white whitespace-nowrap shrink-0 focus-visible:outline-2 focus-visible:outline-blue-500"
          >
            <Download className="h-3.5 w-3.5" aria-hidden="true" />
            Download .md
          </button>
        </div>
      </div>

      {mode === 'raw' ? (
        <pre className="overflow-x-auto p-6 text-xs leading-relaxed text-slate-200 bg-[#0B0F17]">
          <code>{content}</code>
        </pre>
      ) : (
        <article className="p-6 max-w-3xl space-y-3 text-sm leading-relaxed text-slate-300">
          {lines.map((line, index) => {
            const trimmed = line.trim();
            if (!trimmed || trimmed === '---') {
              return <div key={index} className="h-1" />;
            }
            if (trimmed.startsWith('```')) {
              return null;
            }
            if (trimmed.startsWith('# ')) {
              return (
                <h2 key={index} className="text-xl font-bold text-slate-100 pt-1">
                  <InlineText text={trimmed.slice(2)} />
                </h2>
              );
            }
            if (trimmed.startsWith('## ')) {
              return (
                <h3 key={index} className="text-base font-semibold text-slate-100 pt-4">
                  <InlineText text={trimmed.slice(3)} />
                </h3>
              );
            }
            if (trimmed.startsWith('### ')) {
              return (
                <h4 key={index} className="text-sm font-semibold text-slate-100 pt-2">
                  <InlineText text={trimmed.slice(4)} />
                </h4>
              );
            }
            if (trimmed.startsWith('|')) {
              return (
                <div key={index} className="font-mono text-xs text-slate-300 overflow-x-auto">
                  {trimmed}
                </div>
              );
            }
            if (trimmed.startsWith('- ')) {
              return (
                <p key={index} className="pl-4 text-slate-300">
                  <span className="text-slate-500 mr-2" aria-hidden="true">
                    &bull;
                  </span>
                  <InlineText text={trimmed.slice(2).replace(/\*\*/g, '')} />
                </p>
              );
            }
            return (
              <p key={index} className="text-slate-300">
                <InlineText text={trimmed.replace(/\*\*/g, '')} />
              </p>
            );
          })}
        </article>
      )}
    </section>
  );
}

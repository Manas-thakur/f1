import type { ReactNode } from 'react';
import { chapters, REVISION } from './story';

export function Slide({ index, visual, progress = 1, demo = false }: { index: number; visual: ReactNode; progress?: number; demo?: boolean }) {
  const chapter = chapters[index];
  return <article className={`slide-art ${demo ? 'demo' : ''}`}>
    <header><span className="wordmark">AFTERLAP<span className="dot" /></span><span>{chapter.section}</span><span>{String(index + 1).padStart(2, '0')} / {chapters.length}</span></header>
    <div className="copy" style={{ opacity: Math.min(1, progress * 2), transform: `translateY(${(1 - progress) * 16}px)` }}>
      <h1>{chapter.title}</h1>
      <p>{chapter.body}</p>
    </div>
    <div className="visual">{visual}</div>
    {!demo && <div className="visual-labels">{chapter.labels.map((label) => <span key={label}>{label}</span>)}</div>}
    <div className="caption"><span className="caption-line" /><p>{chapter.caption}</p></div>
    <footer><span>{chapter.visual === 'circuit' ? 'CIRCUIT ARTWORK: JULES ROY · CC BY 4.0 · SCALED' : demo ? 'LIVE PRODUCT CAPTURE · ORIGINAL PLAYBACK SPEED' : 'IMPLEMENTATION GUIDE · ILLUSTRATIVE 3D'}</span><span>REPEATABLE SCENARIOS / GUARDED ENERGY</span><span>{REVISION}</span></footer>
  </article>;
}

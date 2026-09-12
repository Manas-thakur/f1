'use client';

import { useEffect, useState } from 'react';
import type { RefObject } from 'react';
import { Rnd } from 'react-rnd';

import { Control } from './Control';
import styles from './race.module.css';

export function ControlDrawer({ parent, open, close, reserve }: {
  parent: RefObject<HTMLElement | null>; open: boolean; close: () => void; reserve: (width: number) => void;
}) {
  const [bounds, setBounds] = useState({ width: 1000, height: 800 });
  const [size, setSize] = useState({ width: 360, height: 700 });
  const [position, setPosition] = useState({ x: 640, y: 0 });
  const [docked, setDocked] = useState(true);
  useEffect(() => {
    const element = parent.current;
    if (!element) {
      return;
    }
    const resize = new ResizeObserver(() => setBounds({
      width: element.clientWidth, height: element.clientHeight,
    }));
    resize.observe(element);
    return () => resize.disconnect();
  }, [parent]);
  const width = Math.min(size.width, bounds.width);
  const height = docked ? bounds.height : Math.min(size.height, bounds.height);
  const x = docked ? bounds.width - width : Math.max(0, Math.min(position.x, bounds.width - width));
  const y = docked ? 0 : Math.max(0, Math.min(position.y, bounds.height - height));
  useEffect(() => reserve(open && docked && bounds.width > 700 ? width : 0),
    [open, docked, width, bounds.width, reserve]);
  if (!open) {
    return null;
  }
  return <Rnd bounds="parent" size={{ width, height }} position={{ x, y }}
    minWidth={Math.min(300, bounds.width)} minHeight={Math.min(260, bounds.height)}
    maxWidth={Math.min(620, bounds.width)} maxHeight={bounds.height}
    dragHandleClassName="race-control-handle" cancel=".panel-action"
    onDragStart={() => { setPosition({ x, y }); setSize({ width, height }); setDocked(false); }}
    onDragStop={(_, data) => setPosition({ x: data.x, y: data.y })}
    onResizeStop={(_, __, element, ___, nextPosition) => {
      setSize({ width: element.offsetWidth, height: element.offsetHeight }); setPosition(nextPosition);
    }}
    enableResizing={docked ? { left: true } : true}
    style={{ display: 'flex', zIndex: 30 }} className={styles.drawer ?? ''}
    data-docked={docked}>
    <div className={styles.drawerHeader}>
      <button type="button" className="race-control-handle" aria-label="Move race controls"
        onKeyDown={(event) => {
          const step = event.shiftKey ? 40 : 10;
          if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) {return;}
          event.preventDefault(); event.stopPropagation(); setDocked(false);
          setPosition({ x: x + (event.key === 'ArrowLeft' ? -step : event.key === 'ArrowRight' ? step : 0),
            y: y + (event.key === 'ArrowUp' ? -step : event.key === 'ArrowDown' ? step : 0) });
        }}>⠿ Race controls</button>
      <button type="button" className="panel-action" onClick={() => setDocked(!docked)}>{docked ? 'Float' : 'Dock'}</button>
      <button type="button" className="panel-action" aria-label="Close race controls" onClick={close}>×</button>
    </div>
    <div className={styles.drawerScroll}><Control /></div>
  </Rnd>;
}

import { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Canvas } from '@react-three/fiber';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import type { Group } from 'three';
import Reveal from 'reveal.js';
import Notes from 'reveal.js/plugin/notes/notes.esm.js';
import 'reveal.js/dist/reveal.css';
import './style.css';
import { chapters, WIDTH, HEIGHT } from './story';
import { Scene } from './Scene';
import { Slide } from './Slide';
import { clips, deckPhotos } from './media';

declare global { interface Window { deck: Reveal.Api; showShahReady: boolean; } }
const frozen = new URLSearchParams(location.search).has('capture');
function Deck() {
  const [active, setActive] = useState(0);
  const [time, setTime] = useState(4);
  const [model, setModel] = useState<Group | null>(null);
  const [error, setError] = useState('');
  useEffect(() => { new GLTFLoader().load(`${import.meta.env.BASE_URL}car.glb`, (gltf) => setModel(gltf.scene), undefined, () => setError('The car asset could not be loaded. Reload the presentation.')); }, []);
  useEffect(() => {
    const deck = new Reveal({ width: WIDTH, height: HEIGHT, margin: 0, hash: true, transition: 'fade', backgroundTransition: 'none', center: false, controls: true, progress: true, plugins: [Notes] });
    window.deck = deck;
    void deck.initialize().then(() => { setActive(deck.getIndices().h); window.showShahReady = true; });
    deck.on('slidechanged', () => setActive(deck.getIndices().h));
    return () => { deck.destroy(); };
  }, []);
  useEffect(() => {
    if (frozen || matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    const start = performance.now();
    const interval = setInterval(() => setTime(((performance.now() - start) / 1000) % 12), 1000 / 30);
    return () => clearInterval(interval);
  }, [active]);
  return <div className="reveal"><div className="slides">{chapters.map((chapter, index) => {
    const photo = deckPhotos.has(index);
    return <section key={chapter.section} aria-label={chapter.section}>
      <Slide index={index} demo={photo} visual={photo ? <img src={`${import.meta.env.BASE_URL}${clips[index]}.jpg`} alt={`Actual product capture: ${chapter.section.toLowerCase()}`} /> : active === index && model ? <Canvas camera={{ fov: 42, near: 0.1, far: 100 }} dpr={1} gl={{ antialias: true, preserveDrawingBuffer: true }}><Scene source={model} kind={chapter.visual} time={time} /></Canvas> : error ? <p role="alert">{error}</p> : null} />
      <a className="source-link" href={`https://github.com/Manas-thakur/f1/blob/dbb00c3/${chapter.sources[0]}`} target="_blank" rel="noreferrer">Implementation source ↗</a>
      <aside className="notes">{chapter.notes}<p>Sources: {chapter.sources.join(', ')}</p></aside>
    </section>;
  })}</div></div>;
}
createRoot(document.getElementById('root')!).render(<Deck />);

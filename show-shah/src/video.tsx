import { useEffect, useState } from 'react';
import { AbsoluteFill, Composition, OffthreadVideo, Sequence, cancelRender, continueRender, delayRender, registerRoot, staticFile, useCurrentFrame } from 'remotion';
import { ThreeCanvas } from '@remotion/three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import type { Group } from 'three';
import { chapters, FPS, SECONDS, WIDTH, HEIGHT } from './story';
import { clips } from './media';
import { Slide } from './Slide';
import { Scene } from './Scene';
import './style.css';

function Film() {
  const frame = useCurrentFrame();
  const index = Math.min(chapters.length - 1, Math.floor(frame / (FPS * SECONDS)));
  const local = frame % (FPS * SECONDS);
  const [model, setModel] = useState<Group | null>(null);
  const [handle] = useState(() => delayRender('Load the reusable car geometry'));
  useEffect(() => {
    new GLTFLoader().load(staticFile('car.glb'), (gltf) => { setModel(gltf.scene); continueRender(handle); }, undefined, (error) => cancelRender(error));
  }, [handle]);
  const clip = clips[index];
  return <AbsoluteFill><Slide index={index} demo={Boolean(clip)} progress={Math.min(1, local / 18)} visual={clip ?
    <Sequence key={clip} from={index * FPS * SECONDS} layout="none"><OffthreadVideo src={staticFile(`${clip}.mp4`)} muted /></Sequence> : model ?
      <ThreeCanvas width={930} height={600} camera={{ fov: 42, near: 0.1, far: 100 }} gl={{ antialias: true }}><Scene source={model} kind={chapters[index].visual} time={local / FPS} /></ThreeCanvas> : null} />
    <div style={{ position: 'absolute', bottom: 0, left: 0, height: 3, width: `${100 * frame / (chapters.length * FPS * SECONDS - 1)}%`, background: '#82e8de' }} />
  </AbsoluteFill>;
}
registerRoot(() => <Composition id="ShowShah" component={Film} durationInFrames={chapters.length * FPS * SECONDS} width={WIDTH} height={HEIGHT} fps={FPS} />);

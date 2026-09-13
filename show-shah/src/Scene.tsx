import { useEffect, useMemo } from 'react';
import { useThree } from '@react-three/fiber';
import { Box3, Color, Mesh, MeshStandardMaterial, Vector3, CatmullRomCurve3, type Group } from 'three';
import type { Chapter } from './story';
import monza from '../../configs/race-circuits/monza.json';

const CYAN = '#82e8de';
const GREY = '#52606b';
const smooth = (t: number) => { const v = Math.max(0, Math.min(1, t)); return v * v * (3 - 2 * v); };

function Car({ source, position, color = CYAN, rotation = 0 }: { source: Group; position: [number, number, number]; color?: string; rotation?: number }) {
  const model = useMemo(() => {
    const copy = source.clone(true);
    copy.traverse((node) => {
      if (!(node instanceof Mesh)) return;
      const original = node.material as MeshStandardMaterial;
      const material = original.clone();
      material.color = new Color(original.name === 'grey' ? color : original.name === 'glass' ? '#b9d2dc' : '#161d24');
      material.metalness = 0.35;
      material.roughness = 0.4;
      node.material = material;
    });
    const box = new Box3().setFromObject(copy);
    const size = box.getSize(new Vector3());
    const center = box.getCenter(new Vector3());
    const scale = 5.4 / Math.max(size.x, size.z);
    copy.position.set(-center.x * scale, -box.min.y * scale, -center.z * scale);
    copy.scale.setScalar(scale);
    return copy;
  }, [source, color]);
  useEffect(() => () => model.traverse((node) => { if (node instanceof Mesh) (node.material as MeshStandardMaterial).dispose(); }), [model]);
  return <group position={position} rotation={[0, rotation, 0]}><primitive object={model} /></group>;
}

function Block({ at, size, color = GREY, opacity = 1 }: { at: [number, number, number]; size: [number, number, number]; color?: string; opacity?: number }) {
  return <mesh position={at}><boxGeometry args={size} /><meshStandardMaterial color={color} roughness={0.45} metalness={0.25} transparent={opacity < 1} opacity={opacity} /></mesh>;
}

function Track({ time }: { time: number }) {
  const curve = useMemo(() => {
    const xs = monza.points.map((p) => p[0]);
    const zs = monza.points.map((p) => p[1]);
    const cx = (Math.min(...xs) + Math.max(...xs)) / 2;
    const cz = (Math.min(...zs) + Math.max(...zs)) / 2;
    return new CatmullRomCurve3(monza.points.map(([x, z]) => new Vector3((x - cx) / 85, 0.1, (z - cz) / 85)), true);
  }, []);
  const point = curve.getPointAt((time / 24) % 1);
  return <group rotation={[0, -0.4, 0]}>
    <mesh><tubeGeometry args={[curve, 500, 0.19, 6, true]} /><meshStandardMaterial color={CYAN} metalness={0.3} roughness={0.35} /></mesh>
    <mesh position={point}><sphereGeometry args={[0.26, 16, 16]} /><meshBasicMaterial color="#ffffff" /></mesh>
  </group>;
}

export function Scene({ source, kind, time }: { source: Group; kind: Chapter['visual']; time: number }) {
  const { camera } = useThree();
  const angle = 0.4 + Math.sin(time * 0.08) * 0.12;
  camera.position.set(12 * Math.sin(angle), kind === 'circuit' ? 15 : 8, kind === 'circuit' ? 12 : 14);
  camera.lookAt(0, 0.6, 0);
  camera.updateProjectionMatrix();
  const progress = smooth((time - 2) / 6);
  const carScene = ['hero', 'race', 'motion', 'screen'].includes(kind);
  return <>
    <ambientLight intensity={1.4} />
    <hemisphereLight args={['#d7f3ff', '#171c24', 2.2]} />
    <directionalLight position={[4, 12, 6]} intensity={3.5} color="#ffffff" />
    <directionalLight position={[-6, 4, -4]} intensity={2.5} color={CYAN} />
    <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.14, 0]}><circleGeometry args={[10, 96]} /><meshStandardMaterial color="#151d24" roughness={0.9} /></mesh>
    {carScene && <group rotation={[0, kind === 'hero' ? -0.6 + time * 0.025 : -0.25, 0]}>
      <Block at={[0, -0.05, 0]} size={[10, 0.05, 16]} color="#202b34" />
      {[-4.6, 4.6].map((x) => <Block key={x} at={[x, 0, 0]} size={[0.06, 0.02, 16]} color={CYAN} />)}
      <Car source={source} position={[kind === 'race' ? -1.8 * Math.sin(progress * Math.PI) : 0, 0, kind === 'race' ? 3 - progress * 6 : 0]} />
      {(kind === 'race' || kind === 'motion') && <Car source={source} position={[2.6, 0, -2]} color="#9cabb8" />}
      {kind === 'motion' && [0, 1, 2, 3].map((i) => <Block key={i} at={[-2.6, 0.05, -5 + i * 3]} size={[0.5, 0.05, 0.5]} color={i <= Math.floor(time / 3) ? CYAN : GREY} />)}
    </group>}
    {kind === 'circuit' && <Track time={time} />}
    {kind === 'battery' && <group rotation={[0, -0.3, 0]}>
      <Block at={[0, 0.1, 0]} size={[6, 0.25, 4.3]} color="#41505c" />
      {Array.from({ length: 8 }, (_, i) => <Block key={i} at={[-2.45 + i * 0.7, 1, 0]} size={[0.5, 1.6, 3.6]} color={i < 7 - Math.floor(progress * 4) ? CYAN : '#28343e'} />)}
      <Block at={[0, 2, 0]} size={[6, 0.12, 4.3]} color={CYAN} opacity={0.14} />
      {Array.from({ length: 4 }, (_, i) => <Block key={i} at={[4.2 + ((time + i) % 3), 0.3, 0]} size={[0.3, 0.3, 0.3]} color={CYAN} />)}
    </group>}
    {kind === 'observations' && <group rotation={[0, -0.2, 0]}>
      {Array.from({ length: 38 }, (_, i) => <Block key={i} at={[(i % 10 - 4.5) * 0.9, 0.5, (Math.floor(i / 10) - 1.5) * 1.05]} size={[0.55, 0.2 + ((i * 7) % 9) * 0.13, 0.55]} color={i % 7 ? CYAN : '#28333d'} />)}
      {Array.from({ length: 38 }, (_, i) => <Block key={`mask${i}`} at={[(i % 10 - 4.5) * 0.9, 0.1, (Math.floor(i / 10) - 1.5) * 1.05]} size={[0.72, 0.06, 0.72]} color={i % 7 ? '#668c95' : '#202932'} />)}
    </group>}
    {['pipeline', 'guard', 'training'].includes(kind) && <group rotation={[0, -0.15, 0]}>
      <Block at={[0, 0.1, 0]} size={[12, 0.06, 0.1]} color={GREY} />
      {[-4, 0, 4].map((x, i) => <group key={x}>
        <Block at={[x, 0.55, 0]} size={[2.1, 0.9, 2.8]} color={i <= Math.floor(time / 3) ? CYAN : GREY} />
        {kind === 'guard' && i === 1 && <>
          <Block at={[x - 1.2, 1.8, 0]} size={[0.15, 3.5, 0.15]} color={CYAN} />
          <Block at={[x + 1.2, 1.8, 0]} size={[0.15, 3.5, 0.15]} color={CYAN} />
          <Block at={[x, 3.5, 0]} size={[2.55, 0.15, 0.15]} color={CYAN} />
        </>}
      </group>)}
      <mesh position={[-6 + (time % 6) * 2, 1.35, 0]}><sphereGeometry args={[0.17, 16, 16]} /><meshBasicMaterial color="#ffffff" /></mesh>
    </group>}
    {kind === 'button' && <group rotation={[0, -0.25, 0]}>
      <Block at={[0, 0.5, 0]} size={[5, 0.9, 4]} color="#34424e" />
      <mesh position={[0, 1.05 - 0.15 * Math.sin(Math.min(1, progress * 2) * Math.PI), 0]}><cylinderGeometry args={[1.1, 1.1, 0.5, 64]} /><meshStandardMaterial color={CYAN} metalness={0.35} roughness={0.3} /></mesh>
      <Block at={[0, 0.5, -4]} size={[0.06, 0.06, 4]} color={CYAN} />
    </group>}
  </>;
}

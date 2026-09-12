import { useEffect, useMemo, useRef } from "react";
import { useThree } from "@react-three/fiber";
import { Color, DoubleSide, Fog, Mesh, MeshStandardMaterial, type Group } from "three";
import { cameraAt } from "../motion";
import { T } from "../theme";

const SCALE = 3.76;
const HALF = 7.4;

export const CameraRig = ({ frame }: { readonly frame: number }) => {
  const { camera, scene } = useThree();
  const cfg = cameraAt(frame);
  useEffect(() => {
    scene.fog = new Fog(new Color(T.sky).getHex(), 60, 210);
    scene.background = new Color(T.sky);
  }, [scene]);
  camera.position.set(cfg.eye[0], cfg.eye[1], cfg.eye[2]);
  camera.lookAt(cfg.target[0], cfg.target[1], cfg.target[2]);
  if ("fov" in camera) {
    (camera as unknown as { fov: number }).fov = (cfg.fov * 180) / Math.PI;
  }
  camera.updateProjectionMatrix();
  return null;
};

export const Lights = () => (
  <>
    <ambientLight intensity={1.7} color="#b3c7db" />
    <hemisphereLight args={["#9cc0e4", "#252d36", 2.0]} />
    <directionalLight position={[-40, 60, 30]} intensity={4.2} color="#ffffff" />
    <directionalLight position={[60, 30, -40]} intensity={1.6} color="#7fb0e8" />
    <pointLight position={[0, 12, 0]} intensity={80} distance={90} color="#ffd9a8" />
  </>
);

export const Track = ({ nearX }: { readonly nearX: number }) => {
  const from = nearX;
  const len = 320;
  const dashes = useMemo(() => {
    const out: number[] = [];
    const period = 14;
    const first = Math.ceil(from / period) * period;
    for (let x = first; x < from + len; x += period) out.push(x);
    return out;
  }, [from]);
  const kerbs = useMemo(() => {
    const out: number[] = [];
    const step = 4;
    const first = Math.ceil(from / step) * step;
    for (let x = first; x < from + len; x += step) out.push(x);
    return out;
  }, [from]);

  return (
    <group>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[from + len / 2, 0, 0]} receiveShadow>
        <planeGeometry args={[len, HALF * 2]} />
        <meshStandardMaterial color="#525c67" roughness={0.9} metalness={0.05} />
      </mesh>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[from + len / 2, -0.02, 0]}>
        <planeGeometry args={[len, HALF * 2 + 40]} />
        <meshStandardMaterial color="#1b2229" roughness={1} />
      </mesh>
      {kerbs.map((x, i) => (
        <group key={x}>
          <mesh rotation={[-Math.PI / 2, 0, 0]} position={[x + 2, 0.01, -HALF - 0.7]}>
            <planeGeometry args={[4, 1.4]} />
            <meshStandardMaterial color={i % 2 === 0 ? "#d7dde3" : "#9c3a40"} roughness={0.8} />
          </mesh>
          <mesh rotation={[-Math.PI / 2, 0, 0]} position={[x + 2, 0.01, HALF + 0.7]}>
            <planeGeometry args={[4, 1.4]} />
            <meshStandardMaterial color={i % 2 === 0 ? "#9c3a40" : "#d7dde3"} roughness={0.8} />
          </mesh>
        </group>
      ))}
      {dashes.map((x) => (
        <mesh key={`d${x}`} rotation={[-Math.PI / 2, 0, 0]} position={[x + 3, 0.012, 0]}>
          <planeGeometry args={[6, 0.3]} />
          <meshStandardMaterial color="#e6ebef" roughness={0.7} />
        </mesh>
      ))}
    </group>
  );
};

export const Car = ({
  source,
  x,
  z,
  body,
  accent,
}: {
  readonly source: Group | null;
  readonly x: number;
  readonly z: number;
  readonly body: string;
  readonly accent: string;
}) => {
  const ref = useRef<Group>(null);
  const cloned = useMemo(() => {
    if (!source) return null;
    const copy = source.clone(true);
    copy.traverse((node) => {
      const mesh = node as Mesh;
      if (!mesh.isMesh) return;
      const mat = mesh.material as MeshStandardMaterial;
      const next = mat.clone();
      if (mat.name === "grey") {
        next.color = new Color(body);
        next.metalness = 0.35;
        next.roughness = 0.42;
      } else if (mat.name === "glass") {
        next.color = new Color(accent);
        next.metalness = 0.2;
        next.roughness = 0.25;
      } else {
        next.color = new Color("#15181c");
        next.roughness = 0.95;
      }
      next.side = DoubleSide;
      mesh.material = next;
    });
    return copy;
  }, [source, body, accent]);

  if (!cloned) return null;
  return (
    <group ref={ref} position={[x, 0, z]} rotation={[0, -Math.PI / 2, 0]} scale={SCALE}>
      <primitive object={cloned} />
    </group>
  );
};

export const Corridor = ({
  originX,
  z,
  colour,
  reach,
  opacity,
}: {
  readonly originX: number;
  readonly z: number;
  readonly colour: string;
  readonly reach: number;
  readonly opacity: number;
}) => {
  if (opacity <= 0) return null;
  return (
    <mesh rotation={[-Math.PI / 2, 0, 0]} position={[originX + 4 + reach / 2, 0.03, z]}>
      <planeGeometry args={[reach, 2.7]} />
      <meshBasicMaterial color={colour} transparent opacity={0.22 * opacity} side={DoubleSide} />
    </mesh>
  );
};

export const Checkpoint = ({ x, opacity }: { readonly x: number; readonly opacity: number }) => {
  if (opacity <= 0) return null;
  const cells = 16;
  const step = (HALF * 2) / cells;
  return (
    <group>
      {Array.from({ length: cells }, (_, i) => (
        <mesh
          key={i}
          rotation={[-Math.PI / 2, 0, 0]}
          position={[x, 0.02, -HALF + step * (i + 0.5)]}
        >
          <planeGeometry args={[2.8, step]} />
          <meshStandardMaterial
            color={i % 2 === 0 ? "#ffffff" : "#12171d"}
            transparent
            opacity={opacity}
            roughness={0.6}
          />
        </mesh>
      ))}
    </group>
  );
};

export const Gate = ({
  x,
  state,
  opacity,
}: {
  readonly x: number;
  readonly state: "pass" | "unknown";
  readonly opacity: number;
}) => {
  if (opacity <= 0) return null;
  const colour = state === "pass" ? "#8acd9e" : "#6b7a88";
  const h = 4.2;
  const segments = state === "unknown" ? 7 : 1;
  const span = HALF * 2;
  return (
    <group position={[x, 0, 0]}>
      {[-HALF, HALF].map((z) => (
        <mesh key={z} position={[0, h / 2, z]}>
          <boxGeometry args={[0.3, h, 0.3]} />
          <meshStandardMaterial
            color={colour}
            emissive={colour}
            emissiveIntensity={0.6}
            transparent
            opacity={opacity}
          />
        </mesh>
      ))}
      {Array.from({ length: segments }, (_, i) => {
        const w = span / (segments * 2 - 1);
        const z = -HALF + w * (i * 2) + w / 2;
        return (
          <mesh key={`b${i}`} position={[0, h, segments === 1 ? 0 : z]}>
            <boxGeometry args={[0.3, 0.3, segments === 1 ? span : w]} />
            <meshStandardMaterial
              color={colour}
              emissive={colour}
              emissiveIntensity={0.6}
              transparent
              opacity={opacity}
            />
          </mesh>
        );
      })}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.04, 0]}>
        <planeGeometry args={[1.6, span]} />
        <meshBasicMaterial color={colour} transparent opacity={0.28 * opacity} side={DoubleSide} />
      </mesh>
    </group>
  );
};

import { AbsoluteFill, staticFile, useCurrentFrame } from "remotion";
import { ThreeCanvas } from "@remotion/three";
import { basisOf, project } from "./three/camera";
import { CameraRig, Car, Checkpoint, Corridor, Gate, Lights, Track } from "./webgl/Scene";
import { useGLTF } from "./webgl/useGltf";
import { cameraAt, fade, ownX, ownZ, rivalX, rivalZ } from "./motion";
import { FONT, K, T, VIDEO } from "./theme";

const LANES = [
  { id: "attack", label: "ATTACK", colour: T.attack, z: -4.6 },
  { id: "prepare", label: "PREPARE", colour: T.prepare, z: -1.55 },
  { id: "defend", label: "DEFEND", colour: T.defend, z: 1.55 },
  { id: "recover", label: "RECOVER", colour: T.recover, z: 4.6 },
] as const;

const CAPS: readonly (readonly [string, number, number])[] = [
  ["ENERGY IS FINITE", 24, 170],
  ["THE RIVAL'S IS A RANGE", 200, 350],
  ["RULES GATE EVERY OPTION", 380, 520],
  ["FOUR FUTURES, PRICED", 548, 700],
  ["JUDGED LATER, NOT AT THE PASS", 762, 880],
];

export const Promo = () => {
  const frame = useCurrentFrame();
  const model = useGLTF(staticFile("raceCarWhite.glb"));
  const cfg = cameraAt(frame);
  const basis = basisOf(cfg);
  const ox = ownX(frame);
  const rx = rivalX(frame);
  const oz = ownZ(frame);
  const rz = rivalZ(frame);

  const ownGauge = fade(frame, 40, 70, 700, 730);
  const rivalGauge = fade(frame, 210, 240, 700, 730);
  const lanes = fade(frame, 556, 590, 716, 746);
  const gates = fade(frame, 392, 420, 520, 548);
  const chosen = frame > 650 ? "prepare" : null;
  const drain = 1 - 0.42 * fade(frame, 690, 790, 900, 901);
  const caption = CAPS.find(([, a, b]) => frame >= a && frame < b);

  const gauge = (x: number, z: number, level: number, band: readonly [number, number] | null, colour: string, opacity: number, key: string) => {
    if (opacity <= 0) return null;
    const p = project(basis, [x, 2.9, z]);
    if (!p.visible) return null;
    const w = 210 * K;
    const h = 26 * K;
    return (
      <div
        key={key}
        style={{
          position: "absolute",
          left: p.x - w / 2,
          top: p.y - h,
          width: w,
          height: h,
          opacity,
          background: "rgba(10,14,18,0.72)",
          border: `${2 * K}px solid ${colour}`,
          boxSizing: "border-box",
        }}
      >
        {band ? (
          <div
            style={{
              position: "absolute",
              left: `${band[0] * 100}%`,
              width: `${(band[1] - band[0]) * 100}%`,
              top: 0,
              bottom: 0,
              background: colour,
              opacity: 0.45,
              borderLeft: `${3 * K}px solid ${colour}`,
              borderRight: `${3 * K}px solid ${colour}`,
            }}
          />
        ) : (
          <div
            style={{
              position: "absolute",
              left: 0,
              top: 0,
              bottom: 0,
              width: `${level * 100}%`,
              background: colour,
            }}
          />
        )}
      </div>
    );
  };

  return (
    <AbsoluteFill style={{ backgroundColor: T.sky }}>
      <ThreeCanvas
        linear
        width={VIDEO.width}
        height={VIDEO.height}
        camera={{ fov: 40, position: [0, 3, 12], near: 0.5, far: 400 }}
        gl={{ antialias: true, toneMappingExposure: 1.25 }}
      >
        <CameraRig frame={frame} />
        <Lights />
        <Track nearX={cfg.eye[0] - 30} />
        {LANES.map((lane, i) => (
          <Corridor
            key={lane.id}
            originX={ox}
            z={lane.z}
            colour={lane.colour}
            reach={46}
            opacity={
              lanes *
              fade(frame, 556 + i * 14, 586 + i * 14, 716, 746) *
              (chosen !== null && chosen !== lane.id ? 0.25 : 1)
            }
          />
        ))}
        <Gate x={ox + 46} state="pass" opacity={gates} />
        <Gate x={ox + 86} state="unknown" opacity={gates} />
        <Checkpoint x={585} opacity={fade(frame, 690, 730, 896, 900)} />
        <Car source={model ? model.scene : null} x={ox} z={oz} body={T.own} accent="#cfe4ff" />
        <Car source={model ? model.scene : null} x={rx} z={rz} body={T.rival} accent="#e8d6f5" />
      </ThreeCanvas>

      {gauge(ox, oz, 0.78 * drain, null, T.own, ownGauge, "own")}
      {gauge(rx, rz, 0, [0.34, 0.63], T.rival, rivalGauge, "rival")}

      {lanes > 0
        ? LANES.map((lane, i) => {
            const a = lanes * fade(frame, 566 + i * 14, 596 + i * 14, 716, 746);
            if (a <= 0) return null;
            const p = project(basis, [ox + 9, 0.5, lane.z]);
            if (!p.visible) return null;
            const dim = chosen !== null && chosen !== lane.id ? 0.32 : 1;
            return (
              <div
                key={lane.id}
                style={{
                  position: "absolute",
                  left: p.x,
                  top: p.y,
                  transform: "translate(-50%, -50%)",
                  fontFamily: FONT.body,
                  fontSize: 26 * K,
                  letterSpacing: `${3 * K}px`,
                  color: lane.colour,
                  opacity: a * dim,
                  textShadow: `0 ${2 * K}px ${8 * K}px rgba(0,0,0,0.7)`,
                  whiteSpace: "nowrap",
                }}
              >
                {lane.label}
              </div>
            );
          })
        : null}

      {caption ? (
        <div
          style={{
            position: "absolute",
            left: 0,
            right: 0,
            top: 120 * K,
            textAlign: "center",
            fontFamily: FONT.body,
            fontSize: 44 * K,
            letterSpacing: `${7 * K}px`,
            color: T.ink,
            opacity: fade(frame, caption[1], caption[1] + 18, caption[2] - 18, caption[2]),
          }}
        >
          {caption[0]}
        </div>
      ) : null}

      {frame >= 836 ? (
        <div
          style={{
            position: "absolute",
            left: 0,
            right: 0,
            top: 940 * K,
            textAlign: "center",
            fontFamily: FONT.body,
            fontSize: 86 * K,
            letterSpacing: `${20 * K}px`,
            color: T.ink,
            opacity: fade(frame, 842, 870, 898, 900),
          }}
        >
          AFTERLAP
        </div>
      ) : null}
    </AbsoluteFill>
  );
};

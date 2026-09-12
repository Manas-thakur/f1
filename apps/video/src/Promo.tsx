import { AbsoluteFill, useCurrentFrame } from "remotion";
import { basisOf } from "./three/camera";
import { Car3D } from "./three/Car3D";
import { Track } from "./scene/Track";
import { Corridors, LANES } from "./scene/Corridors";
import { Checkpoint, Gate, Gauge } from "./scene/Gauge";
import { anchorAt } from "./three/camera";
import { cameraAt, fade, ownX, ownZ, rivalX, rivalZ } from "./motion";
import { FONT, K, T, VIDEO } from "./theme";

const OWN_BODY: readonly [number, number, number] = [62, 74, 88];
const OWN_ACCENT: readonly [number, number, number] = [79, 157, 234];
const RIVAL_BODY: readonly [number, number, number] = [74, 62, 92];
const RIVAL_ACCENT: readonly [number, number, number] = [176, 131, 208];

const CAPS: readonly (readonly [string, number, number])[] = [
  ["ENERGY IS FINITE", 24, 170],
  ["THE RIVAL'S IS A RANGE", 200, 350],
  ["RULES GATE EVERY OPTION", 380, 520],
  ["FOUR FUTURES, PRICED", 548, 690],
  ["JUDGED LATER, NOT AT THE PASS", 760, 880],
];

export const Promo = () => {
  const frame = useCurrentFrame();
  const camera = cameraAt(frame);
  const basis = basisOf(camera);
  const ox = ownX(frame);
  const rx = rivalX(frame);
  const oz = ownZ(frame);
  const rz = rivalZ(frame);

  const ownGauge = fade(frame, 40, 70, 690, 720);
  const rivalGauge = fade(frame, 210, 240, 690, 720);
  const gates = fade(frame, 392, 420, 520, 548);
  const lanes = fade(frame, 556, 590, 712, 742);
  const chosen = frame > 650 ? "prepare" : null;
  const drain = 1 - 0.42 * fade(frame, 690, 790, 900, 901);

  const caption = CAPS.find(([, a, b]) => frame >= a && frame < b);

  return (
    <AbsoluteFill style={{ backgroundColor: T.sky }}>
      <svg
        width={VIDEO.width}
        height={VIDEO.height}
        viewBox={`0 0 ${VIDEO.width} ${VIDEO.height}`}
        style={{ position: "absolute", inset: 0 }}
      >
        <defs>
          <linearGradient id="sky" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="#131a22" />
            <stop offset="1" stopColor={T.deep} />
          </linearGradient>
        </defs>
        <rect width={VIDEO.width} height={VIDEO.height} fill="url(#sky)" />
        <Track basis={basis} nearX={camera.eye[0] + 2.2} />

        <Corridors
          basis={basis}
          originX={ox}
          reach={46}
          alpha={(id) => {
            const i = LANES.findIndex((l) => l.id === id);
            return lanes * fade(frame, 556 + i * 14, 586 + i * 14, 712, 742);
          }}
          chosen={chosen}
        />

        <Checkpoint basis={basis} x={585} opacity={fade(frame, 690, 730, 896, 900)} />
        <Gate basis={basis} x={ox + 34} state="pass" opacity={gates} />
        <Gate basis={basis} x={ox + 62} state="unknown" opacity={gates} />

        {rx > ox ? (
          <>
            <Car3D basis={basis} x={rx} z={rz} body={RIVAL_BODY} accent={RIVAL_ACCENT} />
            <Car3D basis={basis} x={ox} z={oz} body={OWN_BODY} accent={OWN_ACCENT} />
          </>
        ) : (
          <>
            <Car3D basis={basis} x={ox} z={oz} body={OWN_BODY} accent={OWN_ACCENT} />
            <Car3D basis={basis} x={rx} z={rz} body={RIVAL_BODY} accent={RIVAL_ACCENT} />
          </>
        )}

        <Gauge
          basis={basis}
          x={ox}
          z={oz}
          level={0.78 * drain}
          band={null}
          colour={T.own}
          opacity={ownGauge}
        />
        <Gauge
          basis={basis}
          x={rx}
          z={rz}
          level={0}
          band={[0.34, 0.63]}
          colour={T.rival}
          opacity={rivalGauge}
        />

        {lanes > 0
          ? LANES.map((lane, i) => {
              const a = lanes * fade(frame, 566 + i * 14, 596 + i * 14, 712, 742);
              if (a <= 0) return null;
              const p = anchorAt(basis, ox + 13, lane.z, 0.55);
              if (!p.visible) return null;
              const dim = chosen !== null && chosen !== lane.id ? 0.3 : 1;
              return (
                <text
                  key={lane.id}
                  x={p.x}
                  y={p.y}
                  textAnchor="middle"
                  fill={lane.colour}
                  opacity={a * dim}
                  style={{
                    fontFamily: FONT.body,
                    fontSize: 26 * K,
                    letterSpacing: `${2 * K}px`,
                  }}
                >
                  {lane.label}
                </text>
              );
            })
          : null}
      </svg>

      {caption ? (
        <div
          style={{
            position: "absolute",
            left: 0,
            right: 0,
            top: 132 * K,
            textAlign: "center",
            fontFamily: FONT.body,
            fontSize: 42 * K,
            letterSpacing: `${6 * K}px`,
            color: T.ink,
            opacity: fade(frame, caption[1], caption[1] + 18, caption[2] - 18, caption[2]),
          }}
        >
          {caption[0]}
        </div>
      ) : null}

      {frame >= 840 ? (
        <div
          style={{
            position: "absolute",
            left: 0,
            right: 0,
            top: 960 * K,
            textAlign: "center",
            opacity: fade(frame, 846, 872, 898, 900),
          }}
        >
          <div
            style={{
              fontFamily: FONT.body,
              fontSize: 80 * K,
              letterSpacing: `${18 * K}px`,
              color: T.ink,
            }}
          >
            AFTERLAP
          </div>
        </div>
      ) : null}
    </AbsoluteFill>
  );
};

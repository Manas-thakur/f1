import { AbsoluteFill, useCurrentFrame } from "remotion";
import { BEATS } from "./timeline";
import { cameraAt, fade, ownX, ownZ, rivalX, rivalZ } from "./motion";
import { anchor } from "./three/anchor";
import { Car } from "./three/Car";
import { GroundRing } from "./three/Ground";
import { Track } from "./three/Track";
import { Corridor, CorridorLabels } from "./shots/Corridor";
import { RulePack } from "./shots/RulePack";
import { Decision } from "./shots/Decision";
import { Callout, Readout } from "./ui/Callout";
import { Step } from "./ui/Step";
import { FONT, T, VIDEO } from "./theme";

export const Promo = () => {
  const frame = useCurrentFrame();
  const camera = cameraAt(frame);
  const ox = ownX(frame);
  const oz = ownZ(frame);
  const rx = rivalX(frame);
  const rz = rivalZ();
  const centre = (ox + rx) / 2;

  const own = anchor(camera, ox, oz);
  const rival = anchor(camera, rx, rz);

  const energy = fade(frame, 40, 70, 320, 350);
  const ownTag = fade(frame, 60, 90, 330, 360);
  const rivalTag = fade(frame, 190, 220, 330, 360);
  const gapTag = fade(frame, 100, 130, 330, 360);
  const held = fade(frame, 830, 856, 896, 900);

  const beat = BEATS.find((b) => frame >= b.from && frame < b.to) ?? BEATS[0];
  const stepIn = beat ? fade(frame, beat.from, beat.from + 16, beat.to - 14, beat.to) : 0;

  return (
    <AbsoluteFill style={{ backgroundColor: T.paper }}>
      <svg
        width={VIDEO.width}
        height={VIDEO.height}
        viewBox={`0 0 ${VIDEO.width} ${VIDEO.height}`}
        style={{ position: "absolute", inset: 0 }}
      >
        <Track camera={camera} centre={centre} />
        <Corridor camera={camera} frame={frame} originX={ox} />
        <GroundRing
          camera={camera}
          cx={ox}
          cz={oz}
          rx={7.2}
          rz={4.4}
          fill={T.accent}
          fillOpacity={0.09 * energy}
          stroke={T.accent}
          strokeWidth={1.5}
          strokeOpacity={0.5 * energy}
        />
        <GroundRing
          camera={camera}
          cx={rx}
          cz={rz}
          rx={7.2}
          rz={4.4}
          fill={T.aqua}
          fillOpacity={0.07 * rivalTag}
          stroke={T.aqua}
          strokeWidth={1.5}
          strokeOpacity={0.45 * rivalTag}
          dash="10 8"
        />
        <Car camera={camera} x={rx} z={rz} fill={T.surface} stroke={T.aqua} />
        <Car camera={camera} x={ox} z={oz} fill={T.soft} stroke={T.accent} />
      </svg>

      {beat ? (
        <Step n={beat.n} title={beat.title} note={beat.note} opacity={stepIn} />
      ) : null}

      <Callout x={own.x} y={own.y} dx={-150} dy={-130} opacity={ownTag}>
        <Readout label="OWN BATTERY" value="4.12" unit="MJ · measured" />
      </Callout>

      <Callout x={rival.x} y={rival.y} dx={170} dy={-150} opacity={rivalTag} tone={T.aqua}>
        <Readout label="RIVAL BATTERY" value="2.4 – 3.0" unit="MJ · interval" tone={T.aqua} />
      </Callout>

      <Callout x={(own.x + rival.x) / 2} y={own.y + 60} dx={-40} dy={190} opacity={gapTag} tone={T.muted}>
        <Readout label="GAP · OBSERVATION AGE" value="0.82 / 0.27" unit="s" tone={T.muted} />
      </Callout>

      <CorridorLabels camera={camera} frame={frame} originX={ox} />
      <RulePack frame={frame} />
      <Decision frame={frame} />

      <div
        style={{
          position: "absolute",
          left: 88,
          top: 940,
          fontFamily: FONT.body,
          fontSize: 30,
          color: T.good,
          opacity: held,
        }}
      >
        Position retained at the counterattack checkpoint.
      </div>
    </AbsoluteFill>
  );
};

import { AbsoluteFill, useCurrentFrame } from "remotion";
import { BEATS } from "./timeline";
import { cameraAt, fade, ownX, ownZ, rivalX, rivalZ } from "./motion";
import { anchor } from "./three/anchor";
import { Car } from "./three/Car";
import { Track } from "./three/Track";
import { Corridor, CorridorLabels } from "./shots/Corridor";
import { RulePack } from "./shots/RulePack";
import { Decision } from "./shots/Decision";
import { Readout } from "./ui/Callout";
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

  const ownTag = fade(frame, 60, 90, 316, 344);
  const rivalTag = fade(frame, 196, 224, 316, 344);
  const held = fade(frame, 826, 852, 896, 900);

  const beat = BEATS.find((b) => frame >= b.from && frame < b.to) ?? BEATS[0];
  const stepIn = beat ? fade(frame, beat.from, beat.from + 18, beat.to - 16, beat.to) : 0;

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
        <Car camera={camera} x={rx} z={rz} fill="#d9c6e6" stroke={T.aqua} />
        <Car camera={camera} x={ox} z={oz} fill="#bcd4f5" stroke={T.accent} />
      </svg>

      {beat ? <Step n={beat.n} title={beat.title} note={beat.note} opacity={stepIn} /> : null}

      <Readout
        x={own.x}
        y={own.y - 118}
        label="OWN BATTERY · measured"
        value="4.12"
        unit="MJ"
        opacity={ownTag}
      />
      <Readout
        x={rival.x}
        y={rival.y - 118}
        label="RIVAL BATTERY · interval"
        value="2.4 – 3.0"
        unit="MJ"
        opacity={rivalTag}
        tone={T.aqua}
      />

      <CorridorLabels camera={camera} frame={frame} originX={ox} />
      <RulePack frame={frame} />
      <Decision frame={frame} />

      <div
        style={{
          position: "absolute",
          left: 88,
          top: 944,
          fontFamily: FONT.body,
          fontSize: 34,
          color: T.good,
          opacity: held,
        }}
      >
        Position retained at the counterattack checkpoint.
      </div>
    </AbsoluteFill>
  );
};

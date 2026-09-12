export type ScrimProps = {
  readonly left: number;
  readonly top: number;
  readonly width: number;
  readonly height: number;
  readonly strength: number;
  readonly blur?: number | undefined;
  readonly shape?: "radial" | "linear" | undefined;
  readonly opacity?: number | undefined;
  readonly radius?: number | undefined;
};

const maskFor = (shape: "radial" | "linear"): string =>
  shape === "radial"
    ? "radial-gradient(ellipse at center, #000 0%, #000 52%, rgba(0,0,0,0.45) 74%, rgba(0,0,0,0) 92%)"
    : "linear-gradient(to top, #000 0%, #000 46%, rgba(0,0,0,0.4) 78%, rgba(0,0,0,0) 100%)";

export const Scrim = ({
  left,
  top,
  width,
  height,
  strength,
  blur,
  shape,
  opacity,
  radius,
}: ScrimProps) => {
  const s = shape ?? "radial";
  const mask = maskFor(s);
  return (
    <div
      style={{
        position: "absolute",
        left,
        top,
        width,
        height,
        opacity: opacity ?? 1,
        pointerEvents: "none",
        borderRadius: radius ?? 0,
        backgroundColor: `rgba(4,6,8,${strength})`,
        backdropFilter: `blur(${blur ?? 14}px) saturate(0.5) brightness(0.72)`,
        WebkitMaskImage: mask,
        maskImage: mask,
      }}
    />
  );
};

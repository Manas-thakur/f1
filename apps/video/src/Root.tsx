import { Composition } from "remotion";
import { Promo } from "./Promo";
import { VIDEO } from "./theme";

export const Root = () => (
  <Composition
    id="AfterlapPromo"
    component={Promo}
    durationInFrames={VIDEO.durationInFrames}
    fps={VIDEO.fps}
    width={VIDEO.width}
    height={VIDEO.height}
  />
);

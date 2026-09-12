import { useEffect, useState } from "react";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { continueRender, delayRender } from "remotion";
import type { Group } from "three";

export type Loaded = { readonly scene: Group };

export const useGLTF = (url: string): Loaded | null => {
  const [model, setModel] = useState<Loaded | null>(null);
  useEffect(() => {
    const handle = delayRender(`gltf ${url}`);
    const loader = new GLTFLoader();
    loader.load(
      url,
      (gltf) => {
        setModel({ scene: gltf.scene as Group });
        continueRender(handle);
      },
      undefined,
      () => continueRender(handle),
    );
  }, [url]);
  return model;
};

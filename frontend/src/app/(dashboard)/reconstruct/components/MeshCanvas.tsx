"use client";

import { useEffect, Suspense } from "react";
import { Canvas, useLoader, useThree } from "@react-three/fiber";
import { OrbitControls, Center } from "@react-three/drei";
import * as THREE from "three";
import { STLLoader } from "three/examples/jsm/loaders/STLLoader.js";

function STLModel({ url }: { url: string }) {
  const geometry = useLoader(STLLoader, url);

  useEffect(() => {
    if (geometry) {
      geometry.computeVertexNormals();
      geometry.center();
    }
  }, [geometry]);

  const { camera } = useThree();
  useEffect(() => {
    if (geometry) {
      geometry.computeBoundingBox();
      const box = geometry.boundingBox;
      if (box) {
        const size = new THREE.Vector3();
        box.getSize(size);
        const maxDim = Math.max(size.x, size.y, size.z);
        const dist = maxDim * 2;
        camera.position.set(dist * 0.7, dist * 0.5, dist * 0.7);
        camera.lookAt(0, 0, 0);
      }
    }
  }, [geometry, camera]);

  return (
    <Center>
      <mesh geometry={geometry} castShadow receiveShadow>
        <meshStandardMaterial
          color="#6b8cce"
          metalness={0.3}
          roughness={0.4}
          flatShading={false}
        />
      </mesh>
      <mesh geometry={geometry}>
        <meshBasicMaterial
          color="#000000"
          wireframe
          transparent
          opacity={0.05}
        />
      </mesh>
    </Center>
  );
}

export default function MeshCanvas({ url }: { url: string }) {
  return (
    <Canvas shadows camera={{ fov: 45, near: 0.1, far: 10000 }}>
      <ambientLight intensity={0.4} />
      <directionalLight position={[10, 10, 10]} intensity={0.8} castShadow />
      <directionalLight position={[-5, 5, -5]} intensity={0.3} />
      <Suspense fallback={null}>
        <STLModel url={url} />
      </Suspense>
      <OrbitControls makeDefault enableDamping dampingFactor={0.1} />
      <gridHelper args={[200, 20, "#ddd", "#eee"]} position={[0, -50, 0]} />
    </Canvas>
  );
}

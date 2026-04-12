"use client";

import { useRef, useEffect, useState, Suspense } from "react";
import { Canvas, useLoader, useThree } from "@react-three/fiber";
import { OrbitControls, Environment, Center } from "@react-three/drei";
import * as THREE from "three";
import { STLLoader } from "three/examples/jsm/loaders/STLLoader.js";

interface ModelViewerProps {
  file: File | null;
  highlightFaces?: number[];
}

function STLModel({ url, highlightFaces }: { url: string; highlightFaces?: number[] }) {
  const geometry = useLoader(STLLoader, url);
  const meshRef = useRef<THREE.Mesh>(null);

  useEffect(() => {
    if (geometry) {
      geometry.computeVertexNormals();
      geometry.center();
    }
  }, [geometry]);

  // Auto-fit camera to model
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
      <mesh ref={meshRef} geometry={geometry} castShadow receiveShadow>
        <meshStandardMaterial
          color="#6b8cce"
          metalness={0.3}
          roughness={0.4}
          flatShading={false}
        />
      </mesh>
      {/* Wireframe overlay */}
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

export default function ModelViewer({ file, highlightFaces }: ModelViewerProps) {
  const [objectUrl, setObjectUrl] = useState<string | null>(null);

  useEffect(() => {
    if (file && file.name.toLowerCase().endsWith(".stl")) {
      const url = URL.createObjectURL(file);
      setObjectUrl(url);
      return () => URL.revokeObjectURL(url);
    }
    setObjectUrl(null);
  }, [file]);

  if (!objectUrl) {
    return (
      <div className="h-full flex items-center justify-center bg-gray-100 rounded-xl">
        <p className="text-gray-400 text-sm">
          {file ? "STEP preview requires backend conversion" : "Upload a file to preview"}
        </p>
      </div>
    );
  }

  return (
    <div className="h-full rounded-xl overflow-hidden bg-gradient-to-b from-gray-100 to-gray-200">
      <Canvas shadows camera={{ fov: 45, near: 0.1, far: 10000 }}>
        <ambientLight intensity={0.4} />
        <directionalLight position={[10, 10, 10]} intensity={0.8} castShadow />
        <directionalLight position={[-5, 5, -5]} intensity={0.3} />
        <Suspense fallback={null}>
          <STLModel url={objectUrl} highlightFaces={highlightFaces} />
          <Environment preset="studio" />
        </Suspense>
        <OrbitControls makeDefault enableDamping dampingFactor={0.1} />
        <gridHelper args={[200, 20, "#ddd", "#eee"]} position={[0, -50, 0]} />
      </Canvas>
    </div>
  );
}

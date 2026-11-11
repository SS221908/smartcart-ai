import { useEffect, useRef } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import { Float, OrbitControls } from "@react-three/drei";
import * as THREE from "three";
import { gsap } from "gsap";

function SmartCartOrb({ theme, productCount, focus }) {
  const group = useRef();
  const material = useRef();
  const accent = theme === "dark" ? "#62b6ff" : "#0066ff";

  useEffect(() => {
    if (!group.current) return undefined;
    gsap.to(group.current.scale, { x: focus === "cart" ? 1.24 : 1, y: focus === "cart" ? 1.24 : 1, z: focus === "cart" ? 1.24 : 1, duration: 0.8, ease: "power3.out" });
    return undefined;
  }, [focus]);

  useFrame((state, delta) => {
    if (!group.current) return;
    group.current.rotation.y += delta * 0.25;
    group.current.rotation.x = Math.sin(state.clock.elapsedTime * 0.45) * 0.08;
    if (material.current) material.current.emissiveIntensity = 0.45 + Math.sin(state.clock.elapsedTime * 1.8) * 0.08;
  });

  return <group ref={group} position={[0, 0.2, 0]}>
    <Float speed={1.2} rotationIntensity={0.35} floatIntensity={0.6}>
      <mesh castShadow>
        <icosahedronGeometry args={[1.35, 3]} />
        <meshPhysicalMaterial ref={material} color={accent} emissive={accent} emissiveIntensity={0.45} transparent opacity={0.22} roughness={0.12} metalness={0.35} transmission={0.7} thickness={1.4} />
      </mesh>
      <mesh rotation={[Math.PI / 2, 0, 0]} position={[0, -0.1, 0]}>
        <torusGeometry args={[0.9, 0.035, 16, 80]} />
        <meshStandardMaterial color={theme === "dark" ? "#d8edff" : "#0b3f91"} emissive={accent} emissiveIntensity={1.5} />
      </mesh>
    </Float>
    {Array.from({ length: Math.min(productCount, 3) }).map((_, index) => <mesh key={index} position={[-0.45 + index * 0.45, -0.55, 0.5]} rotation={[0, 0, Math.PI / 4]}>
      <boxGeometry args={[0.22, 0.22, 0.22]} />
      <meshStandardMaterial color={index === 1 ? "#ffd166" : "#ffffff"} emissive={index === 1 ? "#ffb300" : accent} emissiveIntensity={0.7} />
    </mesh>)}
  </group>;
}

function ProductStage({ theme, productCount, focus }) {
  return <Canvas shadows dpr={[1, 1.5]} camera={{ position: [0, 0.6, 5.8], fov: 42 }} gl={{ antialias: true }} onCreated={({ gl }) => { gl.toneMapping = THREE.ACESFilmicToneMapping; gl.toneMappingExposure = 1.15; }} fallback={<div className="webgl-fallback" />}>
    <color attach="background" args={[theme === "dark" ? "#071326" : "#eef5ff"]} />
    <ambientLight intensity={theme === "dark" ? 0.65 : 1.1} />
    <directionalLight castShadow position={[3, 5, 4]} intensity={theme === "dark" ? 2.2 : 1.8} color="#d9ecff" />
    <pointLight position={[-3, 1, 2]} intensity={2} color="#4c9dff" />
    <SmartCartOrb theme={theme} productCount={productCount} focus={focus} />
    <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -1.45, 0]} receiveShadow>
      <circleGeometry args={[4.5, 64]} />
      <meshStandardMaterial color={theme === "dark" ? "#0b1c36" : "#dbeafe"} transparent opacity={0.74} roughness={0.8} />
    </mesh>
    <OrbitControls enablePan={false} enableZoom={false} enableRotate={false} />
  </Canvas>;
}

export default function SceneBackdrop({ theme, productCount = 0, focus = "recommendations" }) {
  return <div className="scene-backdrop" aria-hidden="true"><ProductStage theme={theme} productCount={productCount} focus={focus} /></div>;
}

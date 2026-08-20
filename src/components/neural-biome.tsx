import { Canvas, useFrame } from "@react-three/fiber";
import { useMemo, useRef } from "react";
import * as THREE from "three";
import { STATE_VISUALS, type VyomState } from "@/core/vyom-state";

type NeuralBiomeProps = {
  state: VyomState;
};

type NetworkData = {
  points: Float32Array;
  brightPoints: Float32Array;
  edges: Float32Array;
};

function seededRandom(seed: number) {
  let value = seed;
  return () => {
    value = (value * 16807) % 2147483647;
    return (value - 1) / 2147483646;
  };
}

function buildNetwork(): NetworkData {
  const random = seededRandom(481516);
  const nodes = Array.from({ length: 108 }, (_, index) => {
    const angle = random() * Math.PI * 2;
    const radius = 2.05 + Math.pow(random(), 0.72) * 5.5;
    const layerBias = index % 17 === 0 ? 0.5 : 0;
    return new THREE.Vector3(
      Math.cos(angle) * radius * 1.28,
      Math.sin(angle) * radius * 0.73,
      (random() - 0.5) * 3.8 + layerBias,
    );
  });

  const edgeValues: number[] = [];
  nodes.forEach((node, index) => {
    nodes
      .map((candidate, candidateIndex) => ({
        candidate,
        candidateIndex,
        distance: node.distanceTo(candidate),
      }))
      .filter(({ candidateIndex, distance }) => candidateIndex > index && distance < 1.48)
      .sort((a, b) => a.distance - b.distance)
      .slice(0, 3)
      .forEach(({ candidate }) => {
        edgeValues.push(node.x, node.y, node.z, candidate.x, candidate.y, candidate.z);
      });
  });

  return {
    points: new Float32Array(nodes.flatMap((node) => [node.x, node.y, node.z])),
    brightPoints: new Float32Array(
      nodes.filter((_, index) => index % 8 === 0).flatMap((node) => [node.x, node.y, node.z]),
    ),
    edges: new Float32Array(edgeValues),
  };
}

function NeuralNetwork({ state }: NeuralBiomeProps) {
  const groupRef = useRef<THREE.Group>(null);
  const lineMaterialRef = useRef<THREE.LineBasicMaterial>(null);
  const pointMaterialRef = useRef<THREE.PointsMaterial>(null);
  const brightMaterialRef = useRef<THREE.PointsMaterial>(null);
  const data = useMemo(buildNetwork, []);
  const visual = STATE_VISUALS[state];
  const targetColor = useMemo(() => new THREE.Color(visual.color), [visual.color]);

  useFrame(({ clock, pointer }, delta) => {
    const group = groupRef.current;
    if (!group) return;

    group.rotation.y += delta * (0.007 + visual.tempo * 0.011);
    group.rotation.z = Math.sin(clock.elapsedTime * 0.045) * 0.018;
    group.position.x += (pointer.x * 0.2 - group.position.x) * 0.012;
    group.position.y += (pointer.y * 0.11 - group.position.y) * 0.012;

    if (lineMaterialRef.current) {
      lineMaterialRef.current.color.lerp(targetColor, 0.025);
      lineMaterialRef.current.opacity = THREE.MathUtils.lerp(
        lineMaterialRef.current.opacity,
        visual.networkOpacity,
        0.035,
      );
    }
    if (pointMaterialRef.current) {
      pointMaterialRef.current.color.lerp(targetColor, 0.025);
      pointMaterialRef.current.opacity = THREE.MathUtils.lerp(
        pointMaterialRef.current.opacity,
        0.48 + visual.energy * 0.22,
        0.035,
      );
    }
    if (brightMaterialRef.current) {
      brightMaterialRef.current.color.lerp(targetColor, 0.025);
      brightMaterialRef.current.size = THREE.MathUtils.lerp(
        brightMaterialRef.current.size,
        0.075 + visual.energy * 0.04,
        0.035,
      );
    }
  });

  return (
    <group ref={groupRef}>
      <lineSegments>
        <bufferGeometry>
          <bufferAttribute attach="attributes-position" args={[data.edges, 3]} />
        </bufferGeometry>
        <lineBasicMaterial
          ref={lineMaterialRef}
          color="#79aaa8"
          transparent
          opacity={0.14}
          blending={THREE.AdditiveBlending}
          depthWrite={false}
        />
      </lineSegments>
      <points>
        <bufferGeometry>
          <bufferAttribute attach="attributes-position" args={[data.points, 3]} />
        </bufferGeometry>
        <pointsMaterial
          ref={pointMaterialRef}
          color="#8bbab7"
          size={0.032}
          sizeAttenuation
          transparent
          opacity={0.5}
          blending={THREE.AdditiveBlending}
          depthWrite={false}
        />
      </points>
      <points>
        <bufferGeometry>
          <bufferAttribute attach="attributes-position" args={[data.brightPoints, 3]} />
        </bufferGeometry>
        <pointsMaterial
          ref={brightMaterialRef}
          color="#8bc4c0"
          size={0.08}
          sizeAttenuation
          transparent
          opacity={0.5}
          blending={THREE.AdditiveBlending}
          depthWrite={false}
        />
      </points>
    </group>
  );
}

function createHaloTexture() {
  const canvas = document.createElement("canvas");
  canvas.width = 256;
  canvas.height = 256;
  const context = canvas.getContext("2d");
  if (!context) return new THREE.Texture();

  const gradient = context.createRadialGradient(128, 128, 0, 128, 128, 128);
  gradient.addColorStop(0, "rgba(190, 244, 239, 0.36)");
  gradient.addColorStop(0.13, "rgba(112, 208, 205, 0.18)");
  gradient.addColorStop(0.42, "rgba(62, 140, 148, 0.07)");
  gradient.addColorStop(1, "rgba(0, 0, 0, 0)");
  context.fillStyle = gradient;
  context.fillRect(0, 0, 256, 256);

  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

function IntelligenceCore({ state }: NeuralBiomeProps) {
  const rootRef = useRef<THREE.Group>(null);
  const shellRef = useRef<THREE.Mesh>(null);
  const innerMaterialRef = useRef<THREE.MeshPhysicalMaterial>(null);
  const shellMaterialRef = useRef<THREE.MeshBasicMaterial>(null);
  const ringOneRef = useRef<THREE.Mesh>(null);
  const ringTwoRef = useRef<THREE.Mesh>(null);
  const ringThreeRef = useRef<THREE.Mesh>(null);
  const haloMaterialRef = useRef<THREE.SpriteMaterial>(null);
  const lightRef = useRef<THREE.PointLight>(null);
  const waveRefs = useRef<Array<THREE.Mesh | null>>([]);
  const haloTexture = useMemo(createHaloTexture, []);
  const visual = STATE_VISUALS[state];
  const targetColor = useMemo(() => new THREE.Color(visual.color), [visual.color]);
  const targetSecondary = useMemo(() => new THREE.Color(visual.secondary), [visual.secondary]);

  useFrame(({ clock }, delta) => {
    const root = rootRef.current;
    if (!root) return;

    const elapsed = clock.elapsedTime;
    const breath = Math.sin(elapsed * (0.55 + visual.tempo * 0.5));
    const targetScale = 1.06 + visual.energy * 0.03 + breath * (0.008 + visual.energy * 0.009);
    const scale = THREE.MathUtils.lerp(root.scale.x, targetScale, 0.055);
    root.scale.setScalar(scale);
    root.rotation.y += delta * (0.065 + visual.tempo * 0.12);
    root.rotation.x = Math.sin(elapsed * 0.18) * 0.035;

    if (shellRef.current) shellRef.current.rotation.z -= delta * (0.03 + visual.tempo * 0.08);
    if (ringOneRef.current) ringOneRef.current.rotation.z += delta * (0.09 + visual.tempo * 0.2);
    if (ringTwoRef.current) ringTwoRef.current.rotation.x -= delta * (0.07 + visual.tempo * 0.16);
    if (ringThreeRef.current) ringThreeRef.current.rotation.y += delta * (0.035 + visual.tempo * 0.1);

    if (innerMaterialRef.current) {
      innerMaterialRef.current.emissive.lerp(targetSecondary, 0.045);
      innerMaterialRef.current.emissiveIntensity = THREE.MathUtils.lerp(
        innerMaterialRef.current.emissiveIntensity,
        0.34 + visual.energy * 0.68,
        0.04,
      );
    }
    if (shellMaterialRef.current) {
      shellMaterialRef.current.color.lerp(targetColor, 0.045);
      shellMaterialRef.current.opacity = THREE.MathUtils.lerp(
        shellMaterialRef.current.opacity,
        0.18 + visual.energy * 0.22,
        0.04,
      );
    }
    if (haloMaterialRef.current) {
      haloMaterialRef.current.color.lerp(targetColor, 0.035);
      haloMaterialRef.current.opacity = THREE.MathUtils.lerp(
        haloMaterialRef.current.opacity,
        0.14 + visual.energy * 0.12 + breath * 0.018,
        0.04,
      );
    }
    if (lightRef.current) {
      lightRef.current.color.lerp(targetColor, 0.04);
      lightRef.current.intensity = THREE.MathUtils.lerp(
        lightRef.current.intensity,
        0.75 + visual.energy * 1.7,
        0.04,
      );
    }

    waveRefs.current.forEach((wave, index) => {
      if (!wave) return;
      const activeWave = state === "Speaking" || state === "Listening";
      const phase = (elapsed * (0.42 + visual.tempo * 0.2) + index * 0.31) % 1;
      const waveScale = activeWave ? 1 + phase * 0.68 : 1 + index * 0.16;
      wave.scale.setScalar(THREE.MathUtils.lerp(wave.scale.x, waveScale, 0.08));
      const material = wave.material as THREE.MeshBasicMaterial;
      material.color.lerp(targetColor, 0.035);
      material.opacity = THREE.MathUtils.lerp(
        material.opacity,
        activeWave ? (1 - phase) * 0.13 : 0.018,
        0.08,
      );
    });
  });

  return (
    <group ref={rootRef} position={[0, 0.08, 0.8]}>
      <sprite scale={[5.1, 5.1, 1]}>
        <spriteMaterial
          ref={haloMaterialRef}
          map={haloTexture}
          color="#79aaa8"
          transparent
          opacity={0.16}
          blending={THREE.AdditiveBlending}
          depthWrite={false}
        />
      </sprite>

      {[0, 1, 2].map((index) => (
        <mesh
          key={index}
          ref={(node) => {
            waveRefs.current[index] = node;
          }}
          rotation={[Math.PI / 2, 0, 0]}
        >
          <torusGeometry args={[1.48, 0.006, 4, 128]} />
          <meshBasicMaterial
            color="#79aaa8"
            transparent
            opacity={0.018}
            blending={THREE.AdditiveBlending}
            depthWrite={false}
          />
        </mesh>
      ))}

      <mesh>
        <icosahedronGeometry args={[0.7, 4]} />
        <meshPhysicalMaterial
          ref={innerMaterialRef}
          color="#081416"
          emissive="#315d61"
          emissiveIntensity={0.48}
          roughness={0.34}
          metalness={0.18}
          clearcoat={0.55}
          clearcoatRoughness={0.36}
          flatShading
        />
      </mesh>

      <mesh ref={shellRef}>
        <icosahedronGeometry args={[0.89, 2]} />
        <meshBasicMaterial
          ref={shellMaterialRef}
          color="#79aaa8"
          wireframe
          transparent
          opacity={0.24}
          blending={THREE.AdditiveBlending}
          depthWrite={false}
        />
      </mesh>

      <mesh>
        <icosahedronGeometry args={[0.245, 2]} />
        <meshBasicMaterial
          color="#c8eeea"
          transparent
          opacity={0.34}
          blending={THREE.AdditiveBlending}
          depthWrite={false}
        />
      </mesh>

      <mesh ref={ringOneRef} rotation={[Math.PI / 2.8, 0.15, 0]}>
        <torusGeometry args={[1.08, 0.009, 5, 150]} />
        <meshBasicMaterial color={visual.color} transparent opacity={0.34} depthWrite={false} />
      </mesh>
      <mesh ref={ringTwoRef} rotation={[0.2, Math.PI / 2.35, 0.4]}>
        <torusGeometry args={[1.25, 0.005, 4, 150]} />
        <meshBasicMaterial color={visual.color} transparent opacity={0.18} depthWrite={false} />
      </mesh>
      <mesh ref={ringThreeRef} rotation={[Math.PI / 2, 0, 0]}>
        <torusGeometry args={[1.48, 0.004, 4, 180]} />
        <meshBasicMaterial color={visual.color} transparent opacity={0.09} depthWrite={false} />
      </mesh>

      <mesh position={[0, 0, 0.73]}>
        <sphereGeometry args={[0.038, 18, 18]} />
        <meshBasicMaterial color="#e0f7f2" />
      </mesh>
      <pointLight ref={lightRef} color={visual.color} intensity={1.2} distance={5} decay={2} />
    </group>
  );
}

function AmbientSignals({ state }: NeuralBiomeProps) {
  const meshRef = useRef<THREE.InstancedMesh>(null);
  const materialRef = useRef<THREE.MeshBasicMaterial>(null);
  const dummy = useMemo(() => new THREE.Object3D(), []);
  const seeds = useMemo(() => {
    const random = seededRandom(92821);
    return Array.from({ length: 16 }, () => ({
      radius: 2.15 + random() * 4.4,
      angle: random() * Math.PI * 2,
      height: (random() - 0.5) * 3.5,
      direction: random() > 0.5 ? 1 : -1,
      drift: 0.45 + random() * 0.8,
    }));
  }, []);
  const visual = STATE_VISUALS[state];
  const targetColor = useMemo(() => new THREE.Color(visual.color), [visual.color]);

  useFrame(({ clock }) => {
    const mesh = meshRef.current;
    if (!mesh) return;
    const elapsed = clock.elapsedTime;

    seeds.forEach((seed, index) => {
      const angle = seed.angle + elapsed * 0.045 * visual.tempo * seed.direction * seed.drift;
      dummy.position.set(
        Math.cos(angle) * seed.radius * 1.28,
        Math.sin(angle) * seed.radius * 0.7,
        seed.height,
      );
      const pulse = 0.55 + Math.sin(elapsed * 1.2 + index) * 0.2 + visual.energy * 0.28;
      dummy.scale.setScalar(0.018 * pulse);
      dummy.updateMatrix();
      mesh.setMatrixAt(index, dummy.matrix);
    });
    mesh.instanceMatrix.needsUpdate = true;
    materialRef.current?.color.lerp(targetColor, 0.035);
  });

  return (
    <instancedMesh ref={meshRef} args={[undefined, undefined, seeds.length]}>
      <sphereGeometry args={[1, 8, 8]} />
      <meshBasicMaterial
        ref={materialRef}
        color="#79aaa8"
        transparent
        opacity={0.72}
        blending={THREE.AdditiveBlending}
        depthWrite={false}
      />
    </instancedMesh>
  );
}

function LivingScene({ state }: NeuralBiomeProps) {
  return (
    <>
      <ambientLight intensity={0.08} />
      <NeuralNetwork state={state} />
      <AmbientSignals state={state} />
      <IntelligenceCore state={state} />
    </>
  );
}

export function NeuralBiome({ state }: NeuralBiomeProps) {
  return (
    <div className="neural-canvas-shell" aria-hidden="true">
      <Canvas
        dpr={[1, 1.5]}
        camera={{ position: [0, 0, 8.6], fov: 52, near: 0.1, far: 40 }}
        gl={{ antialias: true, alpha: true, powerPreference: "high-performance" }}
        performance={{ min: 0.65 }}
        onCreated={({ gl }) => {
          gl.outputColorSpace = THREE.SRGBColorSpace;
          gl.setClearColor(0x000000, 0);
        }}
      >
        <LivingScene state={state} />
      </Canvas>
    </div>
  );
}

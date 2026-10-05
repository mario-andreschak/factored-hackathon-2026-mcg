import { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import type { WorldProps } from './scenes';

type WorldMaterial = THREE.MeshStandardMaterial;

const material = (color: string, roughness = 0.6, metalness = 0.12, emissive?: string) => new THREE.MeshStandardMaterial({
  color, roughness, metalness, ...(emissive ? { emissive, emissiveIntensity: 0.6 } : {}),
});

/** Original local assets and a procedural fallback; no rig services or asset CDNs. */
export default function ThreeWorld(props: WorldProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const current = useRef(props);
  current.current = props;
  const [failed, setFailed] = useState(false);

  useEffect(() => { setFailed(false); }, [props.avatar]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || failed) return;
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, powerPreference: 'low-power' });
    } catch {
      setFailed(true);
      return;
    }
    const spark = props.avatar === 'spark';
    const scene = new THREE.Scene();
    scene.fog = new THREE.FogExp2(spark ? '#211419' : '#091520', 0.042);
    const camera = new THREE.PerspectiveCamera(38, 1, 0.1, 100);
    camera.position.set(0, 1.3, 8.7);
    camera.lookAt(0, 0.9, 0);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.7));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.15;
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;

    const materials = {
      body: material(spark ? '#be492a' : '#d1d9d4', 0.42, 0.25),
      face: material(spark ? '#e1a376' : '#e6e5d8', 0.58, 0.05),
      dark: material('#102126', 0.3, 0.32),
      hair: material('#211c1a', 0.95, 0),
      accent: material(spark ? '#ff9b40' : '#a6ece0', 0.3, 0.22, spark ? '#b84310' : '#35b8bb'),
      metal: material(spark ? '#eab970' : '#bdad84', 0.29, 0.7),
      floor: material(spark ? '#975c3c' : '#132d34', spark ? 0.94 : 0.38, spark ? 0 : 0.35),
      pillars: material(spark ? '#643122' : '#1c3b44', 0.66, 0.16),
      screen: material(spark ? '#30151b' : '#0c2933', 0.21, 0.38, spark ? '#4d181b' : '#063645'),
      desert: material('#b97452', 1, 0),
      cactus: material('#425644', 0.95, 0),
    };
    const sphere = new THREE.SphereGeometry(1, 40, 28);
    const capsule = new THREE.CapsuleGeometry(0.43, 0.46, 10, 28);
    const eyeGeometry = new THREE.SphereGeometry(1, 20, 16);
    const box = new THREE.BoxGeometry(1, 1, 1);
    const cylinder = new THREE.CylinderGeometry(1, 1, 1, 40);
    const cone = new THREE.ConeGeometry(1, 1, 5);

    function mesh(geometry: THREE.BufferGeometry, surface: WorldMaterial, parent: THREE.Object3D, x: number, y: number, z: number, sx: number, sy: number, sz: number) {
      const object = new THREE.Mesh(geometry, surface);
      object.position.set(x, y, z);
      object.scale.set(sx, sy, sz);
      object.castShadow = true;
      object.receiveShadow = true;
      parent.add(object);
      return object;
    }

    scene.add(new THREE.HemisphereLight(spark ? '#ffc39b' : '#b3e5e9', '#11151b', 2.2));
    const key = new THREE.DirectionalLight(spark ? '#ffe0a7' : '#fff0d0', 4);
    key.position.set(-4, 6, 5);
    key.castShadow = true;
    key.shadow.mapSize.set(1024, 1024);
    key.shadow.camera.left = -6;
    key.shadow.camera.right = 6;
    key.shadow.camera.top = 6;
    key.shadow.camera.bottom = -6;
    key.shadow.normalBias = 0.03;
    scene.add(key);
    const rim = new THREE.PointLight(spark ? '#fb5c30' : '#73ddd3', 22, 13, 2);
    rim.position.set(-2.5, 2.2, -2.3);
    scene.add(rim);
    const fill = new THREE.PointLight(spark ? '#da595f' : '#7d9cee', 12, 14, 2);
    fill.position.set(4, 3, 2);
    scene.add(fill);

    const set = new THREE.Group();
    scene.add(set);
    const floor = mesh(cylinder, materials.floor, set, 0, -1.3, -1.2, 9, 0.16, 8);
    floor.receiveShadow = true;
    const pedestal = mesh(cylinder, materials.pillars, set, -1.35, -1.07, 0, 1.48, 0.27, 1.48);
    mesh(cylinder, materials.metal, set, -1.35, -0.91, 0, 1.47, 0.035, 1.47);
    pedestal.receiveShadow = true;

    const portal = new THREE.Group();
    portal.position.set(-1.35, 1.05, -1.7);
    set.add(portal);
    const ring = new THREE.TorusGeometry(2.17, 0.028, 12, 110);
    const secondRing = new THREE.TorusGeometry(2.48, 0.012, 8, 110);
    if (!spark) {
      mesh(ring, materials.accent, portal, 0, 0, 0, 1, 1, 1);
      mesh(secondRing, materials.metal, portal, 0, 0, -0.1, 1, 1, 1);
    }
    portal.rotation.z = spark ? -0.3 : 0.15;
    if (!spark) {
      mesh(cylinder, materials.pillars, set, 3.1, 0.15, -3.5, 0.32, 3.1, 0.32);
      mesh(cylinder, materials.pillars, set, -4, 0.75, -4, 0.43, 4.3, 0.43);
      mesh(cylinder, materials.metal, set, -4, 2.6, -4, 0.46, 0.05, 0.46);
      mesh(cylinder, materials.metal, set, 3.1, 1.7, -3.5, 0.35, 0.05, 0.35);
    } else {
      // An original desert roadside garage: kinetic and warm instead of a second observatory.
      mesh(box, materials.dark, set, 0, -1.195, -0.5, 18, 0.025, 2.3);
      for (let index = -4; index < 5; index++) mesh(box, materials.metal, set, index*2.5, -1.176, .72, 1.1, .01, .045);
      mesh(box, materials.pillars, set, -.3, 2.45, -3.6, 6.1, .18, 2.3);
      mesh(box, materials.accent, set, -.3, 2.34, -2.45, 6.13, .035, .055);
      mesh(cylinder, materials.metal, set, -3.15, .55, -3.4, .075, 3.65, .075);
      mesh(cylinder, materials.metal, set, 2.6, .55, -3.4, .075, 3.65, .075);
      for (const direction of [-1,1]) {
        const pumpX=direction < 0 ? -3.3 : 3.3;
        mesh(box,materials.body,set,pumpX,-.33,-2.05,.62,1.62,.47);
        mesh(box,materials.face,set,pumpX,.51,-2.05,.7,.19,.51);
        mesh(box,materials.dark,set,pumpX,.03,-1.8,.42,.32,.02);
        mesh(box,materials.accent,set,pumpX,.02,-1.78,.27,.055,.015);
        const hose=new THREE.TorusGeometry(.28,.025,8,24,Math.PI*1.5);
        mesh(hose,materials.dark,set,pumpX+.36,-.4,-1.82,.5,1.6,1);
      }
      const mountainGeometry=new THREE.ConeGeometry(1,1,5);
      const rocks=new THREE.DodecahedronGeometry(1,0);
      mesh(mountainGeometry,materials.desert,set,-6,.08,-8,4.8,4.1,2.5);
      mesh(mountainGeometry,materials.pillars,set,5,-.24,-9,4.6,3.4,2.8);
      mesh(rocks,materials.desert,set,-5,-.6,-4,1.2,.75,1.3);
      for (const x of [-4.9,4.8]) {
        const cactus=new THREE.Group(); cactus.position.set(x,-.9,-3.8); set.add(cactus);
        mesh(cylinder,materials.cactus,cactus,0,.8,0,.12,1.9,.12);
        mesh(sphere,materials.cactus,cactus,0,1.75,0,.12,.12,.12);
        mesh(cylinder,materials.cactus,cactus,.31,1.1,0,.09,.74,.09);
        mesh(sphere,materials.cactus,cactus,.31,1.47,0,.09,.09,.09);
        const branch=mesh(cylinder,materials.cactus,cactus,.17,.75,0,.09,.32,.09); branch.rotation.z=Math.PI/2;
        mesh(cylinder,materials.cactus,cactus,-.32,.63,0,.085,.62,.085);
        const branch2=mesh(cylinder,materials.cactus,cactus,-.16,.32,0,.085,.32,.085); branch2.rotation.z=Math.PI/2;
      }
    }

    // The real browser lives in the app layer. This physical console seats it in the world.
    const console = new THREE.Group();
    console.position.set(2.05, -0.02, -0.5);
    console.rotation.y = -0.16;
    set.add(console);
    mesh(box, materials.pillars, console, 0, -0.91, 0, 2.15, 0.3, 1.16);
    mesh(cylinder, materials.metal, console, 0, -0.37, -0.13, 0.1, 0.88, 0.1);
    mesh(box, materials.dark, console, 0, 0.26, -0.08, 2.24, 1.48, 0.14);
    mesh(box, materials.screen, console, 0, 0.26, 0.01, 2.06, 1.3, 0.025);
    mesh(box, materials.accent, console, -0.72, -0.46, 0.01, 0.27, 0.018, 0.02);

    const actor = new THREE.Group();
    actor.position.set(-1.35, -0.29, 0.28);
    actor.rotation.y = 0.11;
    scene.add(actor);
    mesh(capsule, materials.body, actor, 0, 0.02, 0, 1.15, 1, 0.85);
    mesh(sphere, materials.dark, actor, -0.23, -0.46, 0.11, 0.23, 0.17, 0.34);
    mesh(sphere, materials.dark, actor, 0.23, -0.46, 0.11, 0.23, 0.17, 0.34);
    if (!spark) {
      mesh(sphere, materials.metal, actor, 0, 0.1, 0.37, 0.15, 0.15, 0.025);
      mesh(sphere, materials.accent, actor, 0, 0.1, 0.401, 0.07, 0.07, 0.014);
    } else {
      mesh(box, materials.metal, actor, 0, 0.11, 0.38, 0.025, 0.61, 0.02);
      const collarLeft = mesh(cone, materials.dark, actor, -0.21, 0.47, 0.19, 0.15, 0.3, 0.1);
      collarLeft.rotation.z = -0.7;
      const collarRight = mesh(cone, materials.dark, actor, 0.21, 0.47, 0.19, 0.15, 0.3, 0.1);
      collarRight.rotation.z = 0.7;
    }
    const head = new THREE.Group();
    head.position.y = 1.03;
    actor.add(head);
    mesh(sphere, materials.face, head, 0, 0, 0, 0.76, spark ? 0.87 : 0.8, 0.66);
    if (!spark) {
      mesh(sphere, materials.dark, head, 0, -0.01, 0.56, 0.63, 0.31, 0.17);
      mesh(sphere, materials.metal, head, -0.75, 0, 0, 0.05, 0.2, 0.22);
      mesh(sphere, materials.metal, head, 0.75, 0, 0, 0.05, 0.2, 0.22);
    } else {
      mesh(sphere, materials.face, head, 0, -0.08, 0.62, 0.13, 0.18, 0.16);
      mesh(sphere, materials.hair, head, 0, 0.61, -0.15, 0.72, 0.3, 0.61);
      for (let index = 0; index < 7; index++) {
        const tuft = mesh(cone, materials.hair, head, (index - 3) * 0.17, 0.87 + Math.sin(index) * 0.08, -0.03, 0.17, 0.48, 0.22);
        tuft.rotation.z = -0.3 - index * 0.06;
      }
      // An oversized, crooked road hat gives Spark an original western silhouette.
      const hat = new THREE.Group(); hat.position.set(-.025,.78,-.03); hat.rotation.z=.14; head.add(hat);
      mesh(sphere,materials.metal,hat,0,.14,0,1.01,.075,.8);
      mesh(cylinder,materials.pillars,hat,0,.37,-.03,.5,.5,.44);
      mesh(cylinder,materials.dark,hat,0,.17,-.03,.51,.065,.45);
      const goggle=new THREE.TorusGeometry(.13,.026,8,30);
      mesh(goggle,materials.metal,head,-.25,.1,.64,1.02,.86,1);
      mesh(goggle,materials.metal,head,.25,.1,.64,1.02,.86,1);
      mesh(box,materials.metal,head,0,.12,.657,.22,.022,.023);
      const eyebrowLeft = mesh(box, materials.hair, head, -0.26, 0.25, 0.59, 0.28, 0.06, 0.035);
      eyebrowLeft.rotation.z = -0.22;
      const eyebrowRight = mesh(box, materials.hair, head, 0.26, 0.28, 0.59, 0.28, 0.06, 0.035);
      eyebrowRight.rotation.z = 0.1;
      const earring = new THREE.TorusGeometry(0.09, 0.018, 10, 24);
      mesh(earring, materials.metal, head, -0.76, -0.18, 0.11, 1, 1, 1);
    }
    const eyes = [-1, 1].map(direction => mesh(eyeGeometry, spark ? materials.dark : materials.accent, head, direction * 0.25, spark ? 0.1 : 0.025, spark ? 0.61 : 0.73, spark ? 0.065 : 0.065, spark ? 0.1 : 0.08, 0.028));
    const mouth = mesh(eyeGeometry, spark ? materials.dark : materials.accent, head, spark ? 0.07 : 0, spark ? -0.34 : -0.19, spark ? 0.59 : 0.713, spark ? 0.19 : 0.12, 0.023, 0.025);
    mouth.rotation.z = spark ? 0.12 : 0;
    const arms = [-1, 1].map(direction => {
      const arm = new THREE.Group();
      arm.position.set(direction * 0.48, 0.3, 0);
      arm.rotation.z = direction * 0.28;
      actor.add(arm);
      mesh(capsule, materials.body, arm, direction * 0.05, -0.23, 0, 0.38, 0.64, 0.4);
      mesh(sphere, spark ? materials.face : materials.metal, arm, direction * 0.08, -0.54, 0.02, 0.15, 0.18, 0.15);
      return arm;
    });

    const assetRequest = new AbortController();
    const modelContainer = new THREE.Group();
    scene.add(modelContainer);
    let model: THREE.Group | undefined, mixer: THREE.AnimationMixer | undefined;
    let modelHead: THREE.Object3D | undefined;
    let idleAction: THREE.AnimationAction | undefined, talkAction: THREE.AnimationAction | undefined, gestureAction: THREE.AnimationAction | undefined;
    const morphMeshes: THREE.Mesh[] = [];
    let talkWeight = 0, gestureWeight = 0;
    canvas.dataset.character = 'procedural';
    const disposeDetachedModel = (root: THREE.Object3D) => {
      const geometry = new Set<THREE.BufferGeometry>(), surfaces = new Set<THREE.Material>(), skeletons = new Set<THREE.Skeleton>();
      root.traverse(object => {
        if (object instanceof THREE.Mesh) {
          geometry.add(object.geometry);
          (Array.isArray(object.material) ? object.material : [object.material]).forEach(value => surfaces.add(value));
        }
        if (object instanceof THREE.SkinnedMesh) skeletons.add(object.skeleton);
      });
      geometry.forEach(value => value.dispose()); surfaces.forEach(value => value.dispose()); skeletons.forEach(value => value.dispose());
    };
    let assetDisposed = false;
    if (spark) {
      void fetch(`${import.meta.env.BASE_URL}models/spark.glb`, { signal: assetRequest.signal }).then(async response => {
        if (!response.ok) throw new Error('Character asset unavailable');
        const buffer = await response.arrayBuffer();
        if (assetDisposed) return;
        const asset = await new GLTFLoader().parseAsync(buffer, '');
        if (assetDisposed) { disposeDetachedModel(asset.scene); return; }
        const required = ['Idle', 'Talk', 'Gesture'];
        if (!required.every(name => asset.animations.some(clip => clip.name === name))) { disposeDetachedModel(asset.scene); return; }
        model = asset.scene; model.scale.setScalar(.78); model.position.y = -.63;
        model.traverse(object => {
          if (object instanceof THREE.Mesh) {
            object.castShadow = true; object.receiveShadow = true;
            if (object.morphTargetDictionary && object.morphTargetInfluences) morphMeshes.push(object);
          }
          if (object.name === 'head') modelHead = object;
        });
        mixer = new THREE.AnimationMixer(model);
        idleAction = mixer.clipAction(asset.animations.find(clip => clip.name === 'Idle')!).play();
        talkAction = mixer.clipAction(asset.animations.find(clip => clip.name === 'Talk')!).play().setEffectiveWeight(0);
        gestureAction = mixer.clipAction(asset.animations.find(clip => clip.name === 'Gesture')!).play().setEffectiveWeight(0);
        modelContainer.add(model); actor.visible = false; canvas.dataset.character = 'rigged';
      }).catch(() => { /* The existing expressive character remains available. */ });
    }

    const dustGeometry = new THREE.BufferGeometry();
    const dustPositions = new Float32Array(150 * 3);
    for (let index = 0; index < 150; index++) {
      dustPositions[index * 3] = Math.sin(index * 132.71) * 6;
      dustPositions[index * 3 + 1] = ((index * 0.137) % 1) * 6 - 0.4;
      dustPositions[index * 3 + 2] = Math.cos(index * 77.41) * 4 - 2;
    }
    dustGeometry.setAttribute('position', new THREE.BufferAttribute(dustPositions, 3));
    const dustMaterial = new THREE.PointsMaterial({ color: spark ? '#efb77c' : '#a9d8d9', size: 0.021, transparent: true, opacity: 0.35, depthWrite: false });
    const dust = new THREE.Points(dustGeometry, dustMaterial);
    scene.add(dust);

    let request = 0;
    let last = 0;
    let elapsed = 0;
    let audio = 0;
    let stopped = false;
    const render = (now: number) => {
      if (stopped || document.hidden) return;
      const data = current.current;
      const delta = last ? Math.min((now - last) / 1000, 0.05) : 0;
      last = now;
      if (!data.reducedMotion) elapsed += delta;
      audio = THREE.MathUtils.lerp(audio, Math.max(0, Math.min(1, data.audioLevel)), 0.18);
      const speaking = data.phase === 'speaking';
      const thinking = data.phase === 'thinking';
      const motion = data.reducedMotion ? 0 : 1;
      const speed = spark ? 2.1 : 0.7;
      actor.position.y = -0.29 + Math.sin(elapsed * speed) * (spark ? 0.035 : 0.02) * motion;
      actor.rotation.z = Math.sin(elapsed * speed * 0.5) * (spark ? 0.045 : 0.012) * motion;
      head.rotation.y = THREE.MathUtils.lerp(head.rotation.y, data.pointer.x * 0.16 + Math.sin(elapsed * 0.4) * 0.06 * motion, 0.04);
      head.rotation.x = THREE.MathUtils.lerp(head.rotation.x, data.pointer.y * 0.09 + (thinking ? -0.08 : speaking ? Math.sin(elapsed * 3) * 0.025 * motion : 0), 0.04);
      head.rotation.z = THREE.MathUtils.lerp(head.rotation.z, thinking ? (spark ? 0.15 : -0.08) : Math.sin(elapsed * 0.5) * 0.018 * motion, 0.04);
      const blinkCycle = elapsed % (spark ? 4.2 : 6.3);
      const blink = !data.reducedMotion && blinkCycle > 0.12 && blinkCycle < 0.25 ? 0.1 : 1;
      eyes.forEach(eye => { eye.scale.y = (spark ? 0.1 : 0.08) * blink; });
      mouth.scale.y = speaking ? 0.025 + audio * (spark ? 0.16 : 0.08) : 0.023;
      mouth.scale.x = spark ? .19+audio*.065 : .12;
      mouth.rotation.z = spark ? .12+Math.sin(elapsed*3.2)*audio*.2*motion : 0;
      arms.forEach((arm, index) => {
        const direction = index === 0 ? -1 : 1;
        arm.rotation.z = direction * 0.28 + (speaking && spark ? Math.sin(elapsed * 4 + index * 2) * 0.42 : thinking && index === 1 ? -0.85 : Math.sin(elapsed * 0.8 + index) * 0.035) * motion;
        arm.rotation.x = speaking && spark ? Math.cos(elapsed * 3 + index) * 0.22 * motion : 0;
      });
      if (model && mixer) {
        modelContainer.position.copy(actor.position); modelContainer.quaternion.copy(actor.quaternion);
        talkWeight = THREE.MathUtils.lerp(talkWeight, speaking && motion ? .82 : 0, .1);
        gestureWeight = THREE.MathUtils.lerp(gestureWeight, motion && (thinking || speaking && audio > .5) ? .28 : 0, .08);
        idleAction?.setEffectiveWeight(Math.max(.08, 1 - talkWeight - gestureWeight));
        talkAction?.setEffectiveWeight(talkWeight); gestureAction?.setEffectiveWeight(gestureWeight);
        mixer.update(delta * motion);
        if (modelHead) {
          modelHead.rotation.y += data.pointer.x * .12;
          modelHead.rotation.x += data.pointer.y * .06;
        }
        const blinkAmount = motion && blinkCycle > .1 && blinkCycle < .3 ? Math.sin((blinkCycle - .1) / .2 * Math.PI) : 0;
        for (const mesh of morphMeshes) {
          const targets = mesh.morphTargetDictionary!, values = mesh.morphTargetInfluences!;
          if (targets.MouthOpen !== undefined) values[targets.MouthOpen] = speaking ? Math.min(1, audio * 1.3) : 0;
          if (targets.BlinkL !== undefined) values[targets.BlinkL] = blinkAmount;
          if (targets.BlinkR !== undefined) values[targets.BlinkR] = blinkAmount;
        }
      }
      materials.accent.emissiveIntensity = 0.6 + audio * 0.9;
      rim.intensity = 22 + (speaking ? audio * 8 : 0);
      dust.rotation.y = elapsed * (spark ? 0.021 : 0.006);
      portal.rotation.z = (spark ? -0.3 : 0.15) + elapsed * 0.006 * motion;
      renderer.render(scene, camera);
      request = requestAnimationFrame(render);
    };
    const resize = () => {
      const bounds = canvas.getBoundingClientRect();
      if (bounds.width <= 0 || bounds.height <= 0) return;
      camera.aspect = bounds.width / bounds.height;
      const portrait = camera.aspect < 0.9;
      camera.position.set(portrait ? -1.1 : 0, portrait ? 1.8 : 1.3, portrait ? 11.5 : 8.7);
      camera.lookAt(portrait ? -1.1 : 0, 0.9, 0);
      camera.updateProjectionMatrix();
      renderer.setSize(bounds.width, bounds.height, false);
    };
    const visibility = () => {
      cancelAnimationFrame(request);
      last = 0;
      if (!document.hidden) request = requestAnimationFrame(render);
    };
    const contextLost = (event: Event) => { event.preventDefault(); setFailed(true); };
    const observer = new ResizeObserver(resize);
    observer.observe(canvas);
    document.addEventListener('visibilitychange', visibility);
    canvas.addEventListener('webglcontextlost', contextLost);
    resize();
    request = requestAnimationFrame(render);

    return () => {
      stopped = true;
      assetDisposed = true; assetRequest.abort(); mixer?.stopAllAction();
      if (model) mixer?.uncacheRoot(model);
      cancelAnimationFrame(request);
      observer.disconnect();
      document.removeEventListener('visibilitychange', visibility);
      canvas.removeEventListener('webglcontextlost', contextLost);
      const geometries = new Set<THREE.BufferGeometry>();
      const surfaces = new Set<THREE.Material>();
      const skeletons = new Set<THREE.Skeleton>();
      [sphere,capsule,eyeGeometry,box,cylinder,cone,ring,secondRing].forEach(value=>geometries.add(value));
      Object.values(materials).forEach(value=>surfaces.add(value));
      scene.traverse(object => {
        if (object instanceof THREE.Mesh || object instanceof THREE.Points) {
          geometries.add(object.geometry);
          const values = Array.isArray(object.material) ? object.material : [object.material];
          values.forEach(value => surfaces.add(value));
        }
        if (object instanceof THREE.SkinnedMesh) skeletons.add(object.skeleton);
      });
      geometries.forEach(value => value.dispose());
      surfaces.forEach(value => value.dispose());
      skeletons.forEach(value => value.dispose());
      key.shadow.map?.dispose();
      renderer.dispose();
    };
  }, [props.avatar, failed]);

  if (failed) return <div className="world-three-fallback"><div className="world-fallback-head"><div className="world-fallback-visor"><span /><span /></div></div></div>;
  return <canvas ref={canvasRef} className="world-three-canvas" aria-hidden="true" />;
}

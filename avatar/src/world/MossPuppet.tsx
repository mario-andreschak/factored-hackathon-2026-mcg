import { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { SCENES, type WorldProps } from './scenes';

// Coordinates are top-left image fractions, measured against each final painting.
// These local masks animate the actual painted character, including his face.
const RIGS = [
  { body: [.32, .35, .23, .29], head: [.459, .432, .083, .17], eye: [.469, .336], mouth: [.482, .364] },
  { body: [.285, .365, .15, .20], head: [.366, .43, .055, .11], eye: [.382, .369], mouth: [.392, .39] },
  { body: [.298, .477, .183, .21], head: [.423, .534, .057, .107], eye: [.441, .474], mouth: [.452, .501] },
  { body: [.311, .385, .188, .21], head: [.433, .456, .071, .12], eye: [.449, .383], mouth: [.462, .406] },
  { body: [.24, .389, .139, .17], head: [.325, .444, .06, .11], eye: [.34, .384], mouth: [.35, .404] },
  { body: [.267, .462, .165, .19], head: [.352, .514, .054, .109], eye: [.371, .461], mouth: [.381, .479] },
  { body: [.282, .426, .17, .21], head: [.37, .487, .065, .13], eye: [.388, .408], mouth: [.4, .43] },
  { body: [.314, .427, .18, .22], head: [.433, .49, .072, .14], eye: [.449, .403], mouth: [.463, .427] },
  { body: [.299, .435, .17, .21], head: [.395, .488, .072, .13], eye: [.411, .412], mouth: [.424, .435] },
  { body: [.367, .474, .156, .18], head: [.454, .506, .064, .11], eye: [.469, .437], mouth: [.482, .458] },
];

const vertexShader = `varying vec2 vUv;
void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`;

const fragmentShader = `
precision highp float;
varying vec2 vUv;
uniform sampler2D painting;
uniform sampler2D previous;
uniform vec4 body;
uniform vec4 head;
uniform vec2 eye;
uniform vec2 mouth;
uniform vec2 cover;
uniform vec2 viewCenter;
uniform vec2 pointer;
uniform float time;
uniform float motion;
uniform float speech;
uniform float listening;
uniform float thinking;
uniform float travel;
uniform float fade;

float ellipse(vec2 p, vec2 center, vec2 radius) {
  float d = length((p-center)/radius);
  return 1.0 - smoothstep(0.45, 1.0, d);
}
vec3 samplePainting(vec2 p) { return texture2D(painting, vec2(p.x, 1.0-p.y)).rgb; }

void main() {
  vec2 p = vec2(vUv.x, 1.0-vUv.y);
  p = (p - .5) * cover * .985 + viewCenter;
  p += pointer * vec2(.0035, .0025) * motion;
  float travelWave = sin(travel * 3.14159265);
  p = (p - vec2(.40,.44)) * (1.0 - travelWave * .055 * motion) + vec2(.40,.44);
  p.x += travelWave * .022 * motion;
  vec2 original = p;
  float b = ellipse(p, body.xy, body.zw);
  float h = ellipse(p, head.xy, head.zw);
  float breath = sin(time * .82);
  // The shell expands and settles, trees sway with its living weight.
  p -= (p-body.xy) * breath * .026 * b * motion;
  p.y -= breath * .0045 * b * motion;
  p.x -= sin(time*.46) * .004 * b * motion;
  p.y -= sin(time*2.1)*.004*travelWave*b*motion;
  p.x -= sin(time*1.05)*.003*travelWave*b*motion;
  // A separate neck/head response adds attention, nods, and thoughtful pauses.
  p.x -= (sin(time*.59)*.0038 + pointer.x*.0027) * h * motion;
  p.y -= (cos(time*.63)*.005 + thinking*.0028 + speech*.004) * h * motion;
  p -= vec2(-(p.y-head.y), p.x-head.x) * (sin(time*.51)*.025 + thinking*.027) * h * motion;
  vec3 color = samplePainting(p);

  // The eyelid closes over the painted eye. The iris tracks the visitor subtly.
  float cycle = mod(time + 3.2, 6.7);
  float blink = (smoothstep(5.92,6.03,cycle)-smoothstep(6.12,6.27,cycle))*motion;
  float eyeMask = ellipse(p, eye, vec2(.008,.009));
  vec3 lid = samplePainting(vec2(p.x, eye.y-.013));
  float lidLine = ellipse(p, eye+vec2(0,.002), vec2(.007,.0012));
  lid = mix(lid, vec3(.09,.095,.055), lidLine*.82);
  color = mix(color, lid, eyeMask*blink);
  if (blink < .3) {
    vec3 gaze = samplePainting(p-pointer*vec2(.0013,.0008));
    color = mix(color,gaze,eyeMask*motion);
    float glint = ellipse(p, eye+vec2(.0015,-.001),vec2(.0014,.002));
    color += glint * vec3(.25,.18,.055) * (.18+listening*.38);
  }

  // Audio opens the existing smile, then the jaw follows the voice envelope.
  vec2 lip = p - mouth;
  lip.y += lip.x*.18;
  float opening = max(0.0,speech-.025);
  float mouthMask = 1.0-smoothstep(.74,1.0,length(lip/vec2(.018,.0004+opening*.007)));
  color = mix(color,vec3(.075,.052,.035),mouthMask * min(1.0,opening*10.0));
  // Flow in the river and a breeze in the surrounding leaves are spatially separate.
  float water = smoothstep(.68,.92,original.y) * smoothstep(.43,.7,original.x);
  vec2 waterUv = p + vec2(sin(original.y*340.0 + time*.7)*.0008, sin(original.x*95.0-time*.45)*.0007) * water * motion;
  color = mix(color,samplePainting(waterUv),water*.45);
  vec3 old = texture2D(previous,vec2(original.x,1.0-original.y)).rgb;
  color = mix(old,color,fade);
  gl_FragColor = vec4(color, 1.0);
  #include <tonemapping_fragment>
  #include <colorspace_fragment>
}`;

type Props = WorldProps & { onReady?: () => void; onUnavailable?: () => void };

export default function MossPuppet(props: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const current = useRef(props);
  current.current = props;
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || failed) return;
    let renderer: THREE.WebGLRenderer;
    try { renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: false, powerPreference: 'low-power' }); }
    catch { current.current.onUnavailable?.(); setFailed(true); return; }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    const scene = new THREE.Scene();
    const camera = new THREE.OrthographicCamera(-1,1,1,-1,0,2);
    camera.position.z = 1;
    const loader = new THREE.TextureLoader();
    const textures = new Set<THREE.Texture>();
    const empty = new THREE.DataTexture(new Uint8Array([6,15,17,255]),1,1);
    empty.needsUpdate = true;
    textures.add(empty);
    const uniforms = {
      painting: { value: empty as THREE.Texture }, previous: { value: empty as THREE.Texture },
      body: { value: new THREE.Vector4() }, head: { value: new THREE.Vector4() },
      eye: { value: new THREE.Vector2() }, mouth: { value: new THREE.Vector2() },
      cover: { value: new THREE.Vector2(1,1) }, pointer: { value: new THREE.Vector2() },
      viewCenter: { value: new THREE.Vector2(.5,.5) },
      time: { value: 0 }, motion: { value: 1 }, speech: { value: 0 },
      listening: { value: 0 }, thinking: { value: 0 }, travel: { value: 1 }, fade: { value: 0 },
    };
    const shader = new THREE.ShaderMaterial({ vertexShader, fragmentShader, uniforms, depthTest: false, depthWrite: false });
    const geometry = new THREE.PlaneGeometry(2,2);
    scene.add(new THREE.Mesh(geometry,shader));
    let stopped = false;
    let frame = 0;
    let last = 0;
    let elapsed = 0;
    let index = -1;
    let loading = -1;
    let changeStarted = 0;
    let first = true;
    let travelling = false;
    let width = 1;
    let height = 1;
    const updateCover = () => {
      const image = uniforms.painting.value.image as { width?: number; height?: number };
      const imageRatio = (image?.width || 1672) / (image?.height || 941);
      const screenRatio = width/height;
      uniforms.cover.value.set(screenRatio < imageRatio ? screenRatio/imageRatio : 1, screenRatio > imageRatio ? imageRatio/screenRatio : 1);
      // On narrow screens keep Moss near the center instead of cropping his face.
      uniforms.viewCenter.value.set(screenRatio < .9 ? .39 : .5,.5);
    };
    const load = (next: number) => {
      loading = next;
      const texture = loader.load(`${import.meta.env.BASE_URL}${SCENES[next].image.replace(/^\//,'')}`, () => {
        if (stopped || loading !== next) { texture.dispose(); textures.delete(texture); return; }
        const old = uniforms.previous.value;
        if (old !== empty && old !== uniforms.painting.value) { old.dispose(); textures.delete(old); }
        uniforms.previous.value = first ? texture : uniforms.painting.value;
        uniforms.painting.value = texture;
        const rig = RIGS[next];
        uniforms.body.value.fromArray(rig.body);
        uniforms.head.value.fromArray(rig.head);
        uniforms.eye.value.fromArray(rig.eye);
        uniforms.mouth.value.fromArray(rig.mouth);
        uniforms.fade.value = first ? 1 : 0;
        uniforms.travel.value = first ? 1 : 0;
        index = next;
        loading = -1;
        changeStarted = elapsed;
        travelling = !first;
        first = false;
        updateCover();
        current.current.onReady?.();
      }, undefined, () => { if (!stopped && loading === next) { loading = -1; current.current.onUnavailable?.(); setFailed(true); } });
      texture.colorSpace = THREE.SRGBColorSpace;
      texture.minFilter = THREE.LinearFilter;
      texture.magFilter = THREE.LinearFilter;
      texture.generateMipmaps = false;
      textures.add(texture);
    };
    const render = (now: number) => {
      if (stopped || document.hidden) return;
      const data = current.current;
      const delta = last ? Math.min((now-last)/1000,.05) : 0;
      last = now;
      elapsed += delta;
      const next = ((Math.trunc(data.sceneIndex)%SCENES.length)+SCENES.length)%SCENES.length;
      if (next !== index && next !== loading) load(next);
      uniforms.time.value = data.reducedMotion ? 0 : elapsed;
      uniforms.motion.value = data.reducedMotion ? 0 : 1;
      uniforms.pointer.value.x = THREE.MathUtils.lerp(uniforms.pointer.value.x,data.pointer.x,.028);
      uniforms.pointer.value.y = THREE.MathUtils.lerp(uniforms.pointer.value.y,data.pointer.y,.028);
      const targetSpeech = data.phase==='speaking' ? Math.max(0,Math.min(1,data.audioLevel)) : 0;
      uniforms.speech.value = THREE.MathUtils.lerp(uniforms.speech.value,targetSpeech,.2);
      uniforms.listening.value = THREE.MathUtils.lerp(uniforms.listening.value,data.phase==='listening' ? 1 : 0,.03);
      uniforms.thinking.value = THREE.MathUtils.lerp(uniforms.thinking.value,data.phase==='thinking' ? 1 : 0,.025);
      const travelTime = data.reducedMotion || !travelling ? 1 : Math.min(1,(elapsed-changeStarted)/4.8);
      uniforms.travel.value = travelTime;
      uniforms.fade.value = first ? 0 : travelling ? THREE.MathUtils.smoothstep(travelTime,0.06,0.72) : 1;
      if(travelTime===1) travelling=false;
      renderer.render(scene,camera);
      frame = requestAnimationFrame(render);
    };
    const resize = () => {
      const rect = canvas.getBoundingClientRect();
      width = Math.max(1,rect.width); height = Math.max(1,rect.height);
      renderer.setSize(width,height,false);
      updateCover();
    };
    const visibility = () => { cancelAnimationFrame(frame); last=0; if(!document.hidden) frame=requestAnimationFrame(render); };
    const contextLost = (event: Event) => { event.preventDefault(); current.current.onUnavailable?.(); setFailed(true); };
    const observer = new ResizeObserver(resize);
    observer.observe(canvas);
    document.addEventListener('visibilitychange',visibility);
    canvas.addEventListener('webglcontextlost',contextLost);
    resize();
    frame = requestAnimationFrame(render);
    return () => {
      stopped=true;
      cancelAnimationFrame(frame);
      observer.disconnect();
      document.removeEventListener('visibilitychange',visibility);
      canvas.removeEventListener('webglcontextlost',contextLost);
      textures.forEach(texture=>texture.dispose());
      geometry.dispose(); shader.dispose(); renderer.dispose();
    };
  },[failed]);

  return failed ? null : <canvas ref={canvasRef} className="world-moss-puppet" aria-hidden="true" />;
}

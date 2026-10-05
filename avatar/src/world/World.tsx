import { useEffect, useRef, useState, type CSSProperties } from 'react';
import Atmosphere from './Atmosphere';
import ThreeWorld from './ThreeWorld';
import MossPuppet from './MossPuppet';
import { SCENES, type WorldProps } from './scenes';
import './world.css';

export { SCENES, getScenes, sceneCopy, localizedScenes } from './scenes';
export type { WorldProps } from './scenes';

export default function World(props: WorldProps) {
  const scene = SCENES[((Math.trunc(props.sceneIndex) % SCENES.length) + SCENES.length) % SCENES.length];
  const [active, setActive] = useState<string>(SCENES[0].image);
  const [previous, setPrevious] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [failed, setFailed] = useState(false);
  const [puppetReady, setPuppetReady] = useState(false);
  const activeRef = useRef(active);
  activeRef.current = active;

  useEffect(() => { setPuppetReady(false); }, [props.avatar]);

  useEffect(() => {
    if (props.avatar !== 'moss') return;
    let cancelled = false;
    const image = new Image();
    image.onload = () => {
      if (cancelled) return;
      if (activeRef.current !== scene.image) setPrevious(activeRef.current);
      setActive(scene.image);
      setLoaded(true);
      setFailed(false);
    };
    image.onerror = () => { if (!cancelled) setFailed(true); };
    image.src = `${import.meta.env.BASE_URL}${scene.image.replace(/^\//, '')}`;
    return () => { cancelled = true; image.onload = null; image.onerror = null; };
  }, [scene.image, props.avatar]);

  useEffect(() => {
    if (!previous) return;
    const timer = setTimeout(() => setPrevious(null), props.reducedMotion ? 0 : 1900);
    return () => clearTimeout(timer);
  }, [previous, props.reducedMotion]);

  // Preload only the next painting; avoid loading the entire gallery on mobile.
  useEffect(() => {
    if (!loaded || props.avatar !== 'moss') return;
    const next = SCENES[(SCENES.indexOf(scene) + 1) % SCENES.length];
    const image = new Image();
    image.src = `${import.meta.env.BASE_URL}${next.image.replace(/^\//, '')}`;
  }, [scene, loaded, props.avatar]);

  const style = {
    '--world-x': `${props.reducedMotion ? 0 : props.pointer.x * 8}px`,
    '--world-y': `${props.reducedMotion ? 0 : props.pointer.y * 5}px`,
    '--world-tint': scene.tint,
    '--voice-level': Math.max(0, Math.min(1, props.audioLevel)),
  } as CSSProperties;

  return (
    <div className={`world world--${props.avatar}${props.reducedMotion ? ' world--still' : ''}`} data-phase={props.phase} data-puppet={puppetReady ? 'ready' : 'loading'} style={style} aria-hidden="true">
      {props.avatar === 'moss' ? <>
        <div className="world-paintings">
          {previous && <img className="world-painting world-painting--previous" src={`${import.meta.env.BASE_URL}${previous.replace(/^\//, '')}`} alt="" />}
          <img key={active} className={`world-painting${loaded ? ' world-painting--ready' : ''}`} src={`${import.meta.env.BASE_URL}${active.replace(/^\//, '')}`} alt="" />
        </div>
        <MossPuppet {...props} onReady={() => setPuppetReady(true)} onUnavailable={() => setPuppetReady(false)} />
        {failed && !loaded && <div className="world-fallback-forest"><div className="forest-orb" /><div className="forest-horizon" /></div>}
        <div className="world-ambient-light" />
        <div className="world-fog world-fog--far" />
        <div className="world-fog world-fog--near" />
        <div className="world-water-shimmer" />
        <Atmosphere weather={scene.weather} reducedMotion={props.reducedMotion} audioLevel={props.audioLevel} />
        <div className="world-listening-glow" />
      </> : <ThreeWorld {...props} />}
      <div className="world-vignette" />
      <div className="world-film-grain" />
    </div>
  );
}

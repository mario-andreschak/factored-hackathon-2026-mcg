import { useEffect, useRef, useState } from "react";

/** Honours the operating system's reduced-motion preference, live. */
export function useReducedMotion() {
  const [reduced, setReduced] = useState(
    () => window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  useEffect(() => {
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReduced(query.matches);
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);
  return reduced;
}

/** Animates a number towards `value` on a rAF loop with an ease-out curve.
 *  Returns the target immediately when motion is reduced. */
export function useCountUp(value: number, duration = 900) {
  const reduced = useReducedMotion();
  const [shown, setShown] = useState(reduced ? value : 0);
  const from = useRef(0);

  useEffect(() => {
    if (reduced) {
      setShown(value);
      return;
    }
    const start = performance.now();
    const origin = from.current;
    let frame = 0;
    const tick = (now: number) => {
      const t = Math.min((now - start) / duration, 1);
      const eased = 1 - Math.pow(1 - t, 3);
      setShown(origin + (value - origin) * eased);
      if (t < 1) frame = requestAnimationFrame(tick);
      else from.current = value;
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [value, duration, reduced]);

  return shown;
}

/** True once the element has been scrolled into view, so charts animate when
 *  they are actually seen rather than all at once on load. */
export function useInView<T extends HTMLElement>() {
  const ref = useRef<T | null>(null);
  const [seen, setSeen] = useState(false);
  useEffect(() => {
    const node = ref.current;
    if (!node || seen) return;
    // Without an observer there is no way to know when the element arrives, so
    // the content is revealed immediately. A chart that never fills is worse
    // than a chart that appears without its entrance.
    if (typeof IntersectionObserver === "undefined") { setSeen(true); return; }
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting)) {
        setSeen(true);
        observer.disconnect();
      }
    }, { rootMargin: "0px 0px -8% 0px", threshold: 0.08 });
    observer.observe(node);
    // Safety net: printing, a detached container, or a browser that never
    // reports intersection must not leave the figures stuck at zero.
    const fallback = window.setTimeout(() => setSeen(true), 2500);
    return () => { observer.disconnect(); window.clearTimeout(fallback); };
  }, [seen]);
  return { ref, seen };
}

/** Staggered entrance. `index` becomes a CSS custom property so the delay is
 *  resolved in the stylesheet instead of in inline styles per element. */
export function Reveal(props: {
  children: React.ReactNode; index?: number; className?: string; as?: "div" | "li" | "section";
}) {
  const { children, index = 0, className = "", as = "div" } = props;
  const Tag = as;
  return (
    <Tag className={`reveal ${className}`} style={{ ["--i" as string]: index }}>
      {children}
    </Tag>
  );
}

/** Mounts children only after the first paint so CSS entrance animations run. */
export function useMounted(delay = 0) {
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    const timer = setTimeout(() => setMounted(true), delay);
    return () => clearTimeout(timer);
  }, [delay]);
  return mounted;
}

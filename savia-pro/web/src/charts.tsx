import { useMemo, useState } from "react";
import { useInView, useReducedMotion } from "./motion";

/* Every chart here is hand-built SVG. There is no charting dependency, so the
 * bundle stays small and the exact pixels are reviewable. All of them animate
 * on first scroll into view and skip the animation when the operating system
 * asks for reduced motion. */

const CURVE = 0.32; // Catmull-Rom tension for the flow lines

function smoothPath(points: [number, number][]) {
  if (points.length < 2) return "";
  if (points.length === 2) return `M${points[0][0]},${points[0][1]} L${points[1][0]},${points[1][1]}`;
  let d = `M${points[0][0]},${points[0][1]}`;
  for (let i = 0; i < points.length - 1; i += 1) {
    const p0 = points[i - 1] ?? points[i];
    const p1 = points[i];
    const p2 = points[i + 1];
    const p3 = points[i + 2] ?? p2;
    const c1x = p1[0] + ((p2[0] - p0[0]) * CURVE) / 3;
    const c1y = p1[1] + ((p2[1] - p0[1]) * CURVE) / 3;
    const c2x = p2[0] - ((p3[0] - p1[0]) * CURVE) / 3;
    const c2y = p2[1] - ((p3[1] - p1[1]) * CURVE) / 3;
    d += ` C${c1x},${c1y} ${c2x},${c2y} ${p2[0]},${p2[1]}`;
  }
  return d;
}

export type FlowSeries = {
  key: string; label: string; values: number[]; tone: "in" | "out" | "none";
};

export function FlowChart(props: {
  labels: string[];
  series: FlowSeries[];
  format: (value: number) => string;
  labelFor: (index: number) => string;
  height?: number;
}) {
  const { labels, series, format, labelFor, height = 230 } = props;
  const { ref, seen } = useInView<HTMLDivElement>();
  const reduced = useReducedMotion();
  const [hover, setHover] = useState<number | null>(null);

  const W = 760;
  const H = height;
  const padX = 10;
  const padTop = 16;
  const padBottom = 26;

  const max = useMemo(
    () => Math.max(1, ...series.flatMap((s) => s.values)),
    [series]);

  const n = labels.length;
  const x = (i: number) => (n <= 1 ? W / 2 : padX + (i * (W - padX * 2)) / (n - 1));
  const y = (v: number) => H - padBottom - (v / max) * (H - padTop - padBottom);

  const gridLines = [0, 0.25, 0.5, 0.75, 1].map((f) => ({ f, y: y(max * f) }));

  // Month ticks: show at most eight so the axis never collides with itself.
  const tickEvery = Math.max(1, Math.ceil(n / 8));

  return (
    <div className={`chart ${seen || reduced ? "is-in" : ""}`} ref={ref}>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" preserveAspectRatio="none"
           onMouseLeave={() => setHover(null)}
           onMouseMove={(event) => {
             const box = event.currentTarget.getBoundingClientRect();
             const relative = ((event.clientX - box.left) / box.width) * W;
             const index = Math.round(((relative - padX) / (W - padX * 2)) * (n - 1));
             setHover(Math.min(Math.max(index, 0), n - 1));
           }}>
        <defs>
          {series.map((s) => (
            <linearGradient key={s.key} id={`fill-${s.key}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" className={`grad-${s.tone} grad-top`} />
              <stop offset="100%" className={`grad-${s.tone} grad-bottom`} />
            </linearGradient>
          ))}
        </defs>

        {gridLines.map((line) => (
          <line key={line.f} className="grid" x1={padX} x2={W - padX} y1={line.y} y2={line.y} />
        ))}

        <g className="chart-wipe">
          {series.map((s) => {
            const points = s.values.map((v, i) => [x(i), y(v)] as [number, number]);
            const line = smoothPath(points);
            const area = `${line} L${x(n - 1)},${H - padBottom} L${x(0)},${H - padBottom} Z`;
            return (
              <g key={s.key} className={`flow flow-${s.tone}`}>
                <path d={area} fill={`url(#fill-${s.key})`} className="flow-area" />
                <path d={line} className="flow-line" />
              </g>
            );
          })}
        </g>

        {hover !== null && (
          <g className="cursor">
            <line x1={x(hover)} x2={x(hover)} y1={padTop - 6} y2={H - padBottom} />
            {series.map((s) => (
              <circle key={s.key} cx={x(hover)} cy={y(s.values[hover] ?? 0)} r="3.6"
                      className={`dot dot-${s.tone}`} />
            ))}
          </g>
        )}

        {labels.map((label, i) =>
          i % tickEvery === 0 || i === n - 1 ? (
            <text key={label} className="axis" x={x(i)} y={H - 8}
                  textAnchor={i === 0 ? "start" : i === n - 1 ? "end" : "middle"}>
              {label}
            </text>
          ) : null)}
      </svg>

      {hover !== null && (
        <div className="chart-tip" style={{ ["--x" as string]: `${(x(hover) / W) * 100}%` }}>
          <strong>{labelFor(hover)}</strong>
          {series.map((s) => (
            <span key={s.key} className={`tip-row tone-${s.tone}`}>
              <i /> {s.label}
              <b>{format(s.values[hover] ?? 0)}</b>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

export type Slice = { key: string; label: string; value: number; tone: string };

export function Donut(props: {
  slices: Slice[]; total: number; centreTop: string; centreBottom: string;
}) {
  const { slices, total, centreTop, centreBottom } = props;
  const { ref, seen } = useInView<HTMLDivElement>();
  const reduced = useReducedMotion();
  const ready = seen || reduced;

  const R = 62;
  const circumference = 2 * Math.PI * R;
  let cursor = 0;

  return (
    <div className={`donut ${ready ? "is-in" : ""}`} ref={ref}>
      <svg viewBox="0 0 160 160" role="img">
        <circle className="donut-track" cx="80" cy="80" r={R} />
        {slices.map((slice, index) => {
          const fraction = total > 0 ? slice.value / total : 0;
          const length = fraction * circumference;
          const offset = -cursor * circumference;
          cursor += fraction;
          return (
            <circle key={slice.key} cx="80" cy="80" r={R}
                    className={`donut-arc tone-${slice.tone}`}
                    strokeDasharray={ready ? `${length} ${circumference - length}` : `0 ${circumference}`}
                    strokeDashoffset={offset}
                    style={{ ["--d" as string]: `${index * 55}ms` }} />
          );
        })}
      </svg>
      <div className="donut-centre">
        <strong>{centreTop}</strong>
        <span>{centreBottom}</span>
      </div>
    </div>
  );
}

export function Sparkline(props: { values: number[]; tone?: "in" | "out" | "none" }) {
  const { values, tone = "none" } = props;
  const { ref, seen } = useInView<HTMLSpanElement>();
  const reduced = useReducedMotion();
  if (values.length < 2) return <span className="spark is-empty" ref={ref} />;

  const W = 110;
  const H = 30;
  const max = Math.max(...values, 1);
  const min = Math.min(...values, 0);
  const span = max - min || 1;
  const points = values.map((v, i) => [
    (i * W) / (values.length - 1),
    H - 3 - ((v - min) / span) * (H - 6),
  ] as [number, number]);

  return (
    <span className={`spark tone-${tone} ${seen || reduced ? "is-in" : ""}`} ref={ref}>
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" aria-hidden="true">
        <path d={`${smoothPath(points)} L${W},${H} L0,${H} Z`} className="spark-area" />
        <path d={smoothPath(points)} className="spark-line" />
      </svg>
    </span>
  );
}

export function Meter(props: {
  label: string; value: number; of: number; caption: string; tone?: string; index?: number;
}) {
  const { label, value, of, caption, tone = "warn", index = 0 } = props;
  const { ref, seen } = useInView<HTMLDivElement>();
  const reduced = useReducedMotion();
  const ratio = of > 0 ? Math.min(value / of, 1) : 0;
  return (
    <div className={`meter ${seen || reduced ? "is-in" : ""}`} ref={ref}>
      <div className="meter-head">
        <span>{label}</span>
        <b>{caption}</b>
      </div>
      <div className="meter-track">
        <i className={`tone-${tone}`}
           style={{ ["--w" as string]: `${(ratio * 100).toFixed(2)}%`,
                    ["--d" as string]: `${index * 70}ms` }} />
      </div>
    </div>
  );
}

export function BarList(props: {
  rows: { key: string; label: string; value: number; caption: string; tone?: string }[];
}) {
  const { ref, seen } = useInView<HTMLDivElement>();
  const reduced = useReducedMotion();
  const max = Math.max(1, ...props.rows.map((r) => r.value));
  return (
    <div className={`bars ${seen || reduced ? "is-in" : ""}`} ref={ref}>
      {props.rows.map((row, index) => (
        <div className="bar-row" key={row.key}>
          <span className="bar-label">{row.label}</span>
          <span className="bar-track">
            <i className={`tone-${row.tone ?? "brand"}`}
               style={{ ["--w" as string]: `${((row.value / max) * 100).toFixed(2)}%`,
                        ["--d" as string]: `${index * 55}ms` }} />
          </span>
          <b className="bar-value">{row.caption}</b>
        </div>
      ))}
    </div>
  );
}

/** Shows a minimum-average-maximum range. Used for merchants that charge more
 *  than once, where a single "amount" would be a fiction. */
export function SpreadBar(props: { min: number; avg: number; max: number; format: (v: number) => string }) {
  const { min, avg, max, format } = props;
  const { ref, seen } = useInView<HTMLDivElement>();
  const reduced = useReducedMotion();
  const span = max - min || 1;
  const position = ((avg - min) / span) * 100;
  return (
    <div className={`spread ${seen || reduced ? "is-in" : ""}`} ref={ref}>
      <span className="spread-min">{format(min)}</span>
      <span className="spread-track">
        <i className="spread-fill" />
        <i className="spread-avg" style={{ ["--p" as string]: `${position.toFixed(1)}%` }} />
      </span>
      <span className="spread-max">{format(max)}</span>
    </div>
  );
}

/**
 * Savia Lite - charts.
 *
 * Hand-built inline SVG: no charting library, no canvas, no web fonts. Each
 * chart is given a text alternative, and every shape carries a <title> so a
 * pointer and a screen reader get the same figure.
 *
 * The charts only ever draw sums of the rows on screen. They never draw a
 * balance, a projection or a prediction.
 */

const NS = "http://www.w3.org/2000/svg";

function svgEl(tag, attrs = {}) {
  const el = document.createElementNS(NS, tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === null || value === undefined) continue;
    el.setAttribute(key, String(value));
  }
  return el;
}

function titled(el, text) {
  const title = svgEl("title");
  title.textContent = text;
  el.append(title);
  return el;
}

/**
 * Grouped bars: money in, money out and undetermined per month.
 * `series` is [{ month, inflow, outflow, undetermined }], oldest first.
 */
export function monthlyBars(series, options) {
  const { labelFor, valueFor, legend, emptyText } = options;
  const wrap = document.createElement("div");
  wrap.className = "chart chart-bars";

  if (!series.length) {
    wrap.append(emptyState(emptyText));
    return wrap;
  }

  const width = 100;
  const height = 42;
  const padBottom = 7;
  const usable = height - padBottom - 2;
  const peak = Math.max(
    ...series.map((m) => Math.max(m.inflow, m.outflow, m.undetermined)),
    1,
  );
  const slot = width / series.length;
  const barWidth = Math.min(slot / 4.4, 2.6);

  const svg = svgEl("svg", {
    viewBox: `0 0 ${width} ${height}`,
    preserveAspectRatio: "none",
    role: "img",
    "aria-label": options.ariaLabel,
    class: "bars-svg",
  });

  // Baseline.
  svg.append(svgEl("line", {
    x1: 0, y1: height - padBottom, x2: width, y2: height - padBottom, class: "axis",
  }));

  series.forEach((month, index) => {
    const centre = slot * index + slot / 2;
    const bars = [
      { key: "inflow", value: month.inflow, cls: "bar-in", offset: -1.15 },
      { key: "outflow", value: month.outflow, cls: "bar-out", offset: 0 },
      { key: "undetermined", value: month.undetermined, cls: "bar-unknown", offset: 1.15 },
    ];
    for (const bar of bars) {
      if (bar.value <= 0) continue;
      const h = Math.max((bar.value / peak) * usable, 0.5);
      const rect = svgEl("rect", {
        x: centre + bar.offset * barWidth - barWidth / 2,
        y: height - padBottom - h,
        width: barWidth,
        height: h,
        rx: 0.5,
        class: `bar ${bar.cls}`,
      });
      titled(rect, `${labelFor(month.month)} · ${legend[bar.key]}: ${valueFor(bar.value)}`);
      svg.append(rect);
    }

    const text = svgEl("text", {
      x: centre,
      y: height - padBottom + 5,
      "text-anchor": "middle",
      class: "bar-label",
    });
    text.textContent = labelFor(month.month);
    svg.append(text);
  });

  wrap.append(svg);
  wrap.append(chartLegend([
    { cls: "bar-in", label: legend.inflow },
    { cls: "bar-out", label: legend.outflow },
    { cls: "bar-unknown", label: legend.undetermined },
  ]));
  return wrap;
}

/**
 * Donut of outgoing money by category, with the unclassified remainder always
 * drawn as its own visible slice rather than quietly dropped.
 * `slices` is [{ label, value, cls }].
 */
export function donut(slices, options) {
  const { valueFor, centreLabel, centreValue, emptyText, ariaLabel } = options;
  const wrap = document.createElement("div");
  wrap.className = "chart chart-donut";

  const total = slices.reduce((sum, slice) => sum + slice.value, 0);
  if (!total) {
    wrap.append(emptyState(emptyText));
    return wrap;
  }

  const size = 42;
  const centre = size / 2;
  const radius = 17;
  const circumference = 2 * Math.PI * radius;

  const svg = svgEl("svg", {
    viewBox: `0 0 ${size} ${size}`,
    role: "img",
    "aria-label": ariaLabel,
    class: "donut-svg",
  });

  svg.append(svgEl("circle", {
    cx: centre, cy: centre, r: radius, class: "donut-track",
    fill: "none", "stroke-width": 6,
  }));

  let offset = 0;
  for (const slice of slices) {
    if (slice.value <= 0) continue;
    const fraction = slice.value / total;
    const arc = svgEl("circle", {
      cx: centre,
      cy: centre,
      r: radius,
      fill: "none",
      "stroke-width": 6,
      "stroke-dasharray": `${(fraction * circumference).toFixed(3)} ${circumference.toFixed(3)}`,
      "stroke-dashoffset": (-offset * circumference).toFixed(3),
      transform: `rotate(-90 ${centre} ${centre})`,
      class: `donut-arc ${slice.cls}`,
    });
    titled(arc, `${slice.label}: ${valueFor(slice.value)}`);
    svg.append(arc);
    offset += fraction;
  }

  const inner = document.createElement("div");
  inner.className = "donut-centre";
  const label = document.createElement("span");
  label.className = "donut-centre-label";
  label.textContent = centreLabel;
  const value = document.createElement("strong");
  value.className = "donut-centre-value";
  value.textContent = centreValue;
  inner.append(value, label);

  const stage = document.createElement("div");
  stage.className = "donut-stage";
  stage.append(svg, inner);
  wrap.append(stage);
  return wrap;
}

/** A horizontal proportion bar, used for the data-quality panel. */
export function meter(fraction, options = {}) {
  const wrap = document.createElement("div");
  wrap.className = `meter ${options.cls || ""}`.trim();
  wrap.setAttribute("role", "img");
  if (options.ariaLabel) wrap.setAttribute("aria-label", options.ariaLabel);
  const fill = document.createElement("span");
  fill.className = "meter-fill";
  fill.style.width = `${Math.max(0, Math.min(1, fraction)) * 100}%`;
  wrap.append(fill);
  return wrap;
}

function chartLegend(entries) {
  const list = document.createElement("ul");
  list.className = "chart-legend";
  for (const entry of entries) {
    const item = document.createElement("li");
    const swatch = document.createElement("span");
    swatch.className = `swatch ${entry.cls}`;
    swatch.setAttribute("aria-hidden", "true");
    const text = document.createElement("span");
    text.textContent = entry.label;
    item.append(swatch, text);
    list.append(item);
  }
  return list;
}

function emptyState(text) {
  const empty = document.createElement("p");
  empty.className = "chart-empty";
  empty.textContent = text;
  return empty;
}

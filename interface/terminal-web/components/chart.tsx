"use client";

import {
  AreaSeries,
  CandlestickSeries,
  ColorType,
  createChart,
  HistogramSeries,
  LineSeries,
  type IChartApi,
  type ISeriesApi,
  type SeriesType,
  type Time,
} from "lightweight-charts";
import { useEffect, useRef } from "react";
import type { Indicator, Point } from "@/lib/types";

const COLORS = {
  text: "#9aa6b8", grid: "#161b26", border: "#1f2735", up: "#3fcf8e", down: "#f26d78", line: "#f0b44c",
  overlays: ["#5fa8ff", "#b78cff", "#3fcf8e", "#f26d78", "#9aa6b8", "#f0b44c"],
};

const day = (iso: string) => iso.slice(0, 10) as Time;

/**
 * Price chart (TradingView Lightweight Charts, Apache-2.0). The library's attribution logo stays
 * visible, as its license notice requires.
 */
export function PriceChart({ points, indicators = [], mode, height }: {
  points: Point[];
  indicators?: Indicator[];
  mode: "candles" | "line";
  height?: number;
}) {
  const container = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  useEffect(() => {
    if (!container.current) return;
    const chart = createChart(container.current, {
      autoSize: true,
      localization: { locale: "en-GB" },
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: COLORS.text,
        fontFamily: "var(--font-geist-mono), ui-monospace, monospace",
        fontSize: 11,
        attributionLogo: true,
      },
      grid: { vertLines: { color: COLORS.grid }, horzLines: { color: COLORS.grid } },
      rightPriceScale: { borderColor: COLORS.border },
      timeScale: { borderColor: COLORS.border, rightOffset: 2 },
      crosshair: { mode: 0 },
      handleScale: { axisPressedMouseMove: true },
    });
    chartRef.current = chart;
    return () => {
      chart.remove();
      chartRef.current = null;
    };
  }, []);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    const hasOhlc = points.some((p) => p.o !== null && p.h !== null && p.l !== null);
    const created: ISeriesApi<SeriesType>[] = [];

    if (mode === "candles" && hasOhlc) {
      const series = chart.addSeries(CandlestickSeries, {
        upColor: COLORS.up, downColor: COLORS.down, wickUpColor: COLORS.up, wickDownColor: COLORS.down,
        borderVisible: false,
      });
      series.setData(points.map((p) => ({ time: day(p.t), open: p.o ?? p.v, high: p.h ?? p.v, low: p.l ?? p.v,
                                          close: p.v })));
      created.push(series);
    } else {
      const series = chart.addSeries(AreaSeries, {
        lineColor: COLORS.line, lineWidth: 2, topColor: "rgba(240,180,76,0.18)",
        bottomColor: "rgba(240,180,76,0)", priceLineVisible: true,
      });
      series.setData(points.map((p) => ({ time: day(p.t), value: p.v })));
      created.push(series);
    }

    if (points.some((p) => p.vol)) {
      const volume = chart.addSeries(HistogramSeries, {
        priceScaleId: "volume", priceFormat: { type: "volume" }, lastValueVisible: false,
        priceLineVisible: false,
      });
      chart.priceScale("volume").applyOptions({ scaleMargins: { top: 0.85, bottom: 0 } });
      volume.setData(points.map((p, i) => ({
        time: day(p.t), value: p.vol ?? 0,
        color: i > 0 && p.v < points[i - 1].v ? "rgba(242,109,120,0.35)" : "rgba(63,207,142,0.35)",
      })));
      created.push(volume);
    }

    let color = 0;
    for (const indicator of indicators) {
      for (const [name, line] of Object.entries(indicator.lines)) {
        if (indicator.kind === "rsi") continue; // an oscillator needs its own scale; shown as a figure instead
        const series = chart.addSeries(LineSeries, {
          color: COLORS.overlays[color % COLORS.overlays.length], lineWidth: 1, priceLineVisible: false,
          lastValueVisible: false, crosshairMarkerVisible: false,
          lineStyle: name === "upper" || name === "lower" ? 2 : 0,
        });
        series.setData(points.flatMap((p, i) => (line[i] === null || line[i] === undefined ? []
          : [{ time: day(p.t), value: line[i] as number }])));
        created.push(series);
      }
      color += 1;
    }
    chart.timeScale().fitContent();
    return () => {
      for (const series of created) {
        try {
          chart.removeSeries(series);
        } catch {
          /* the chart was already disposed */
        }
      }
    };
  }, [points, indicators, mode]);

  return <div ref={container} className="h-full w-full" style={height ? { height } : undefined} />;
}

/** A small inline trend for tables. Pure SVG, no library. */
export function Sparkline({ values, width = 72, height = 20 }: { values: number[]; width?: number; height?: number }) {
  if (values.length < 2) return <span className="inline-block" style={{ width, height }} />;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const path = values
    .map((v, i) => `${i === 0 ? "M" : "L"}${((i / (values.length - 1)) * width).toFixed(1)},${(
      height - 1 - ((v - min) / span) * (height - 2)).toFixed(1)}`)
    .join("");
  const up = values[values.length - 1] >= values[0];
  return (
    <svg width={width} height={height} aria-hidden="true">
      <path d={path} fill="none" stroke={up ? COLORS.up : COLORS.down} strokeWidth="1.2" />
    </svg>
  );
}

export type LineSeries = { name: string; color?: string; points: { t: string; v: number }[] };

/** Several lines on one scale (portfolio against benchmark, equity curves). */
export function LineChart({ series, percent = false }: { series: LineSeries[]; percent?: boolean }) {
  const container = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!container.current) return;
    const chart = createChart(container.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: COLORS.text,
                fontFamily: "var(--font-geist-mono), ui-monospace, monospace", fontSize: 11, attributionLogo: true },
      grid: { vertLines: { color: COLORS.grid }, horzLines: { color: COLORS.grid } },
      rightPriceScale: { borderColor: COLORS.border },
      timeScale: { borderColor: COLORS.border },
      localization: { locale: "en-GB", ...(percent ? { priceFormatter: (v: number) => `${v.toFixed(1)}%` } : {}) },
    });
    const palette = [COLORS.line, COLORS.overlays[0], COLORS.overlays[1], COLORS.overlays[2]];
    series.forEach((line, index) => {
      const added = chart.addSeries(LineSeries, { color: line.color ?? palette[index % palette.length],
                                                  lineWidth: index === 0 ? 2 : 1, priceLineVisible: false,
                                                  title: line.name });
      added.setData(line.points.map((p) => ({ time: day(p.t), value: p.v })));
    });
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [series, percent]);
  return <div ref={container} className="h-full w-full" />;
}

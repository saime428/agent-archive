import { useEffect, useRef } from "react";
import type { ChatPhase } from "./chat/state";

type Point = { x: number; y: number; phase: number; drift: number };

export function canvasParameters(phase: ChatPhase) {
  switch (phase) {
    case "stream":
      return { speed: 1.45, reach: 158, alpha: 0.28, pull: 0.08 };
    case "tool":
      return { speed: 1.9, reach: 132, alpha: 0.34, pull: 0.14 };
    case "approval":
      return { speed: 0.32, reach: 118, alpha: 0.42, pull: 0.22 };
    case "final":
      return { speed: 0.22, reach: 176, alpha: 0.22, pull: 0.04 };
    case "error":
      return { speed: 0.58, reach: 92, alpha: 0.34, pull: -0.08 };
    default:
      return { speed: 0.5, reach: 142, alpha: 0.18, pull: 0.03 };
  }
}

export function ContextField({ phase, themeKey, enabled }: { phase: ChatPhase; themeKey: string; enabled: boolean }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !enabled) return;
    const context = canvas.getContext("2d", { alpha: true });
    if (!context) {
      canvas.dataset.fallback = "true";
      return;
    }

    const reduced = matchMedia("(prefers-reduced-motion: reduce)");
    let width = 1;
    let height = 1;
    let frame = 0;
    let pointCount = 42;
    let visible = !document.hidden;
    let previous = performance.now();
    let left = 0;
    let top = 0;
    const pointer = { x: 0.72, y: 0.38, active: false };
    const points: Point[] = Array.from({ length: 42 }, (_, index) => ({
      x: ((index * 73) % 101) / 100,
      y: ((index * 47 + 17) % 97) / 96,
      phase: index * 0.67,
      drift: 0.4 + (index % 7) * 0.08,
    }));

    const resize = () => {
      const bounds = canvas.getBoundingClientRect();
      width = Math.max(1, bounds.width);
      height = Math.max(1, bounds.height);
      left = bounds.left;
      top = bounds.top;
      pointCount = width < 480 ? 26 : width < 960 ? 34 : 42;
      const ratio = Math.min(devicePixelRatio || 1, 1.5);
      canvas.width = Math.round(width * ratio);
      canvas.height = Math.round(height * ratio);
      context.setTransform(ratio, 0, 0, ratio, 0, 0);
    };

    const draw = (time: number) => {
      const params = canvasParameters(phase);
      const styles = getComputedStyle(document.documentElement);
      const accent = styles.getPropertyValue("--accent").trim() || "#7c86f5";
      const text = styles.getPropertyValue(phase === "error" ? "--danger" : "--text-faint").trim() || accent;
      const elapsed = reduced.matches ? 0 : time * 0.00012 * params.speed;
      const focusX = (pointer.active ? pointer.x : 0.72) * width;
      const focusY = (pointer.active ? pointer.y : 0.38) * height;
      context.clearRect(0, 0, width, height);

      const positions: Array<{ x: number; y: number }> = [];
      for (let index = 0; index < pointCount; index += 1) {
        const point = points[index];
        const wave = Math.sin(elapsed + point.phase) * 18 * point.drift;
        const baseX = point.x * width + wave;
        const baseY = point.y * height + Math.cos(elapsed * 0.8 + point.phase) * 14;
        const dx = focusX - baseX;
        const dy = focusY - baseY;
        const distance = Math.hypot(dx, dy) || 1;
        const influence = Math.max(0, 1 - distance / Math.max(width, height));
        positions.push({
          x: baseX + dx * influence * params.pull,
          y: baseY + dy * influence * params.pull,
        });
      }

      context.lineWidth = 0.75;
      for (let index = 0; index < positions.length; index += 1) {
        for (let sibling = index + 1; sibling < positions.length; sibling += 1) {
          const a = positions[index];
          const b = positions[sibling];
          const distance = Math.hypot(a.x - b.x, a.y - b.y);
          if (distance > params.reach) continue;
          context.globalAlpha = (1 - distance / params.reach) * params.alpha;
          context.strokeStyle = index % 5 === 0 ? accent : text;
          context.beginPath();
          context.moveTo(a.x, a.y);
          context.lineTo(b.x, b.y);
          context.stroke();
        }
      }

      positions.forEach((point, index) => {
        context.globalAlpha = 0.18 + (index % 4) * 0.07;
        context.fillStyle = index % 6 === 0 ? accent : text;
        context.beginPath();
        context.arc(point.x, point.y, index % 6 === 0 ? 1.8 : 1, 0, Math.PI * 2);
        context.fill();
      });
      context.globalAlpha = 1;
      canvas.dataset.frame = reduced.matches ? "static" : "active";
    };

    const tick = (time: number) => {
      if (!visible || reduced.matches) return;
      if (time - previous >= 1000 / 60) {
        draw(time);
        previous = time;
      }
      frame = requestAnimationFrame(tick);
    };

    const start = () => {
      cancelAnimationFrame(frame);
      draw(performance.now());
      if (visible && !reduced.matches) frame = requestAnimationFrame(tick);
    };
    const onPointerMove = (event: PointerEvent) => {
      pointer.x = (event.clientX - left) / Math.max(1, width);
      pointer.y = (event.clientY - top) / Math.max(1, height);
      pointer.active = true;
    };
    const onVisibility = () => {
      visible = !document.hidden;
      start();
    };
    const onReduced = () => start();
    const observer = new ResizeObserver(() => {
      resize();
      start();
    });

    observer.observe(canvas);
    addEventListener("pointermove", onPointerMove, { passive: true });
    document.addEventListener("visibilitychange", onVisibility);
    reduced.addEventListener("change", onReduced);
    resize();
    start();

    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      removeEventListener("pointermove", onPointerMove);
      document.removeEventListener("visibilitychange", onVisibility);
      reduced.removeEventListener("change", onReduced);
    };
  }, [phase, themeKey, enabled]);

  return enabled ? <canvas ref={canvasRef} className="context-field" aria-hidden="true" /> : null;
}

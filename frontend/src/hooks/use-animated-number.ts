import { useEffect, useRef, useState } from "react";

const DURATION_MS = 400;

/**
 * Animate a numeric value from its previous to its current value.
 *
 * Uses requestAnimationFrame with an ease-out curve so dashboard stat
 * cards transition smoothly when data refreshes in the background.
 */
export function useAnimatedNumber(target: number): number {
  const [display, setDisplay] = useState(target);
  const prev = useRef(target);
  const raf = useRef(0);

  useEffect(() => {
    const from = prev.current;
    prev.current = target;

    if (from === target) return;

    const start = performance.now();

    function tick(now: number) {
      const t = Math.min((now - start) / DURATION_MS, 1);
      // ease-out quad
      const eased = 1 - (1 - t) * (1 - t);
      setDisplay(Math.round(from + (target - from) * eased));
      if (t < 1) raf.current = requestAnimationFrame(tick);
    }

    raf.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf.current);
  }, [target]);

  return display;
}

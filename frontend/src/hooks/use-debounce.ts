import { useEffect, useState } from "react";

/**
 * Debounce a value by the given delay (ms).
 *
 * Useful for search inputs — prevents firing a query on every keystroke.
 */
export function useDebounce<T>(value: T, delay: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);
  return debounced;
}

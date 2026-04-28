import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useAnimatedNumber } from "@/hooks/use-animated-number";

describe("useAnimatedNumber", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("returns the initial value immediately", () => {
    const { result } = renderHook(() => useAnimatedNumber(42));
    expect(result.current).toBe(42);
  });

  it("animates to a new value over time", async () => {
    const { result, rerender } = renderHook(
      ({ value }) => useAnimatedNumber(value),
      { initialProps: { value: 0 } },
    );

    expect(result.current).toBe(0);

    rerender({ value: 100 });

    // After full animation duration (400ms + buffer), value should reach target
    await act(async () => {
      vi.advanceTimersByTime(500);
    });

    expect(result.current).toBe(100);
  });

  it("stays at target when value does not change", () => {
    const { result, rerender } = renderHook(
      ({ value }) => useAnimatedNumber(value),
      { initialProps: { value: 50 } },
    );

    rerender({ value: 50 });
    expect(result.current).toBe(50);
  });
});

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { formatRelativeTime } from "@/lib/utils";

describe("formatRelativeTime", () => {
  const NOW = new Date("2026-05-01T12:00:00Z");

  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(NOW);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("returns 'just now' for a date a few seconds ago", () => {
    const d = new Date(NOW.getTime() - 30_000);
    expect(formatRelativeTime(d)).toBe("just now");
  });

  it("returns minutes ago for dates < 1 hour", () => {
    const d = new Date(NOW.getTime() - 5 * 60_000);
    expect(formatRelativeTime(d)).toBe("5m ago");
  });

  it("returns hours ago for dates < 1 day", () => {
    const d = new Date(NOW.getTime() - 3 * 3600_000);
    expect(formatRelativeTime(d)).toBe("3h ago");
  });

  it("returns days ago for dates < 1 week", () => {
    const d = new Date(NOW.getTime() - 4 * 86_400_000);
    expect(formatRelativeTime(d)).toBe("4d ago");
  });

  it("returns locale date string for dates >= 1 week ago", () => {
    const d = new Date(NOW.getTime() - 10 * 86_400_000);
    expect(formatRelativeTime(d)).toBe(d.toLocaleDateString());
  });

  it("returns 'just now' for a date a few seconds in the future", () => {
    const d = new Date(NOW.getTime() + 30_000);
    expect(formatRelativeTime(d)).toBe("just now");
  });

  it("returns 'in Xm' for future dates < 1 hour", () => {
    const d = new Date(NOW.getTime() + 10 * 60_000);
    expect(formatRelativeTime(d)).toBe("in 10m");
  });

  it("returns 'in Xh' for future dates < 1 day", () => {
    const d = new Date(NOW.getTime() + 2 * 3600_000);
    expect(formatRelativeTime(d)).toBe("in 2h");
  });

  it("returns 'in Xd' for future dates >= 1 day", () => {
    const d = new Date(NOW.getTime() + 3 * 86_400_000);
    expect(formatRelativeTime(d)).toBe("in 3d");
  });

  it("returns 'unknown' for an invalid date string", () => {
    expect(formatRelativeTime("not-a-date")).toBe("unknown");
  });

  it("accepts a string date", () => {
    const d = new Date(NOW.getTime() - 2 * 60_000);
    expect(formatRelativeTime(d.toISOString())).toBe("2m ago");
  });
});

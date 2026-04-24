import { lazy, type LazyExoticComponent, type ComponentType } from "react";

/**
 * Central registry mapping plugin routes to lazy-loaded page components.
 *
 * When a new plugin page is added, register it here. The route key must match
 * the `view_route` value returned by the backend plugin metadata (without
 * leading slash for React Router path matching).
 *
 * App.tsx iterates over this map to generate <Route> elements dynamically,
 * so no changes to App.tsx are needed for new plugin pages.
 */
export const pluginRoutes: Record<
  string,
  LazyExoticComponent<ComponentType<unknown>>
> = {
  rules: lazy(() => import("@/pages/rules")),
  spam: lazy(() => import("@/pages/spam")),
  newsletters: lazy(() => import("@/pages/newsletters")),
  labeling: lazy(() => import("@/pages/labeling")),
  "smart-folders": lazy(() => import("@/pages/smart-folders")),
  coupons: lazy(() => import("@/pages/coupons")),
  calendar: lazy(() => import("@/pages/calendar")),
  "auto-reply": lazy(() => import("@/pages/auto-reply")),
  summaries: lazy(() => import("@/pages/summaries")),
  contacts: lazy(() => import("@/pages/contacts")),
  notifications: lazy(() => import("@/pages/notifications")),
};

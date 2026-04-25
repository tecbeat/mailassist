import { useEffect } from "react";

const APP_NAME = "mailassist";

/**
 * Sets `document.title` to `"<title> — mailassist"` on mount,
 * and restores the base title on unmount.
 */
export function usePageTitle(title: string) {
  useEffect(() => {
    const prev = document.title;
    document.title = title ? `${title} — ${APP_NAME}` : APP_NAME;
    return () => {
      document.title = prev;
    };
  }, [title]);
}

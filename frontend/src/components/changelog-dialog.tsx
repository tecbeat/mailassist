import { useEffect, useState } from "react";
import { Check, Sparkles } from "lucide-react";

import { AppDialog } from "@/components/app-dialog";
import { customInstance } from "@/services/client";

interface ChangelogResponse {
  version: string;
  entries: Record<string, string>;
}

/** Render a markdown changelog entry as simple HTML. Trusted content only. */
function ChangelogContent({ markdown }: { markdown: string }) {
  const lines = markdown.split("\n");
  const elements: React.ReactNode[] = [];
  let listItems: string[] = [];
  let key = 0;

  const flushList = () => {
    if (listItems.length > 0) {
      elements.push(
        <ul key={key++} className="list-disc pl-5 space-y-1 text-sm">
          {listItems.map((item, i) => (
            <li key={i} dangerouslySetInnerHTML={{ __html: formatInline(item) }} />
          ))}
        </ul>,
      );
      listItems = [];
    }
  };

  for (const line of lines) {
    const headingMatch = line.match(/^### (.+)/);
    if (headingMatch?.[1]) {
      flushList();
      elements.push(
        <h4 key={key++} className="text-sm font-semibold mt-3 mb-1">
          {headingMatch[1]}
        </h4>,
      );
      continue;
    }

    const listMatch = line.match(/^- (.+)/);
    if (listMatch?.[1]) {
      listItems.push(listMatch[1]);
      continue;
    }

    if (line.trim() === "") {
      flushList();
      continue;
    }

    flushList();
    elements.push(
      <p key={key++} className="text-sm" dangerouslySetInnerHTML={{ __html: formatInline(line) }} />,
    );
  }
  flushList();

  return <div className="space-y-1">{elements}</div>;
}

/** Convert bold markdown and links to HTML. Trusted content only. */
function formatInline(text: string): string {
  return text
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\[(.+?)]\((.+?)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer" class="underline">$1</a>');
}

export function ChangelogDialog() {
  const [open, setOpen] = useState(false);
  const [data, setData] = useState<ChangelogResponse | null>(null);

  useEffect(() => {
    let cancelled = false;

    customInstance<{ data: ChangelogResponse }>("/api/changelog")
      .then((res) => {
        if (cancelled) return;
        const changelog = res.data;
        if (Object.keys(changelog.entries).length > 0) {
          setData(changelog);
          setOpen(true);
        }
      })
      .catch(() => {
        // Feature disabled or unavailable — skip silently
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const handleDismiss = () => {
    if (data) {
      customInstance("/api/changelog/dismiss", { method: "POST" }).catch(() => {
        // Best-effort — if the server is unreachable the dialog simply
        // re-appears on the next page load.
      });
    }
    setOpen(false);
  };

  if (!data) return null;

  return (
    <AppDialog
      open={open}
      onOpenChange={(v) => !v && handleDismiss()}
      title={
        <span className="flex items-center gap-2">
          <Sparkles className="h-5 w-5" aria-hidden />
          What&apos;s New
        </span>
      }
      description={
        data.version.startsWith("v") ? data.version : `v${data.version}`
      }
      primaryLabel="Got it"
      primaryIcon={<Check />}
      onPrimaryClick={handleDismiss}
      contentClassName="min-h-[360px] flex flex-col"
    >
      <div className="overflow-y-auto flex-1 pr-2">
        {Object.entries(data.entries).map(([version, content]) => (
          <div key={version}>
            <h3 className="text-sm font-semibold text-muted-foreground mb-2">
              {version.startsWith("v") ? version : `v${version}`}
            </h3>
            <ChangelogContent markdown={content} />
          </div>
        ))}
      </div>
    </AppDialog>
  );
}

import { useEffect, useState } from "react";
import { Sparkles } from "lucide-react";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { customInstance } from "@/services/client";

const STORAGE_KEY = "mailassist-last-seen-version";

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
        const lastSeen = localStorage.getItem(STORAGE_KEY);
        if (lastSeen !== changelog.version) {
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
      localStorage.setItem(STORAGE_KEY, data.version);
    }
    setOpen(false);
  };

  if (!data) return null;

  // Show entries for the current version, or all entries if current version not found
  const currentEntry = data.entries[data.version];
  const entriesToShow = currentEntry
    ? { [data.version]: currentEntry }
    : data.entries;

  return (
    <Dialog open={open} onOpenChange={(v) => !v && handleDismiss()}>
      <DialogContent className="max-w-md max-h-[80vh] flex flex-col" aria-describedby="changelog-description">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Sparkles className="h-5 w-5" />
            What&apos;s New
          </DialogTitle>
          <DialogDescription id="changelog-description">
            mailassist {data.version.startsWith("v") ? data.version : `v${data.version}`}
          </DialogDescription>
        </DialogHeader>

        <div className="overflow-y-auto flex-1 pr-2">
          {Object.entries(entriesToShow).map(([version, content]) => (
            <div key={version}>
              <ChangelogContent markdown={content} />
            </div>
          ))}
        </div>

        <DialogFooter>
          <Button onClick={handleDismiss} className="w-full sm:w-auto">
            Okay, Let&apos;s Go!
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

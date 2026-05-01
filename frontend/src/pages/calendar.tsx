import { useState } from "react";
import { usePageTitle } from "@/hooks/use-page-title";
import { Info } from "lucide-react";

import { useGetConfigApiCalendarConfigGet } from "@/services/api/calendar/calendar";

import { PageHeader } from "@/components/layout/page-header";
import {
  PluginSettingsDialog,
  PluginSettingsButton,
} from "@/components/plugin-settings-dialog";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { unwrapResponse } from "@/lib/utils";
import type { CalDAVConfigResponse } from "@/types/api";

import { CalDavConfigForm } from "@/components/calendar/caldav-config-form";
import { CalendarEventsList } from "@/components/calendar/calendar-events-list";

export default function CalendarPage() {
  usePageTitle("Calendar");

  const [settingsOpen, setSettingsOpen] = useState(false);

  const configQuery = useGetConfigApiCalendarConfigGet();
  const config = unwrapResponse<CalDAVConfigResponse | null>(configQuery.data);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Calendar Extraction"
        description="Events extracted from emails by the AI calendar plugin."
        actions={
          <div className="flex items-center gap-2">
            <PluginSettingsButton onClick={() => setSettingsOpen(true)} />
          </div>
        }
      />

      {/* Events list */}
      <Card>
        <CardHeader>
          <CardTitle>Extracted Events</CardTitle>
          <CardDescription>
            Calendar events will appear here as they are extracted from your incoming emails.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <CalendarEventsList />
        </CardContent>
      </Card>

      {/* Info card */}
      <Card>
        <CardContent className="flex items-start gap-3 pt-6">
          <Info className="mt-0.5 h-5 w-5 shrink-0 text-blue-500" />
          <div className="text-sm text-muted-foreground">
            <p className="font-medium text-foreground">How calendar integration works</p>
            <p className="mt-1">
              When the AI processes incoming emails, it automatically detects date/time
              references and event-like content. Relevant events are created in your
              configured CalDAV calendar. Configure your CalDAV connection in the{" "}
              <button
                type="button"
                className="font-medium text-foreground underline-offset-4 hover:underline"
                onClick={() => setSettingsOpen(true)}
              >
                Settings
              </button>{" "}
              dialog.
            </p>
          </div>
        </CardContent>
      </Card>

      {config?.updated_at && (
        <p className="text-xs text-muted-foreground">
          CalDAV last configured: {new Date(config.updated_at).toLocaleString()}
        </p>
      )}

      {/* CalDAV settings dialog */}
      <PluginSettingsDialog
        open={settingsOpen}
        onOpenChange={setSettingsOpen}
        title="CalDAV Configuration"
        description="Enter your CalDAV server credentials to enable calendar event creation from emails."
      >
        <CalDavConfigForm onSaved={() => setSettingsOpen(false)} />
      </PluginSettingsDialog>
    </div>
  );
}

import { useEffect } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod/v4";
import { FlaskConical, Save } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";

import {
  useGetConfigApiCalendarConfigGet,
  useUpdateConfigApiCalendarConfigPut,
  useTestConfigApiCalendarConfigTestPost,
  getGetConfigApiCalendarConfigGetQueryKey,
} from "@/services/api/calendar/calendar";

import { AppButton } from "@/components/app-button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { QueryError } from "@/components/query-error";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";
import { unwrapResponse } from "@/lib/utils";
import type { CalDAVConfigResponse, CalDAVTestResponse } from "@/types/api";

const calendarSchema = z.object({
  caldav_url: z.string().min(1, "CalDAV URL is required").max(500),
  default_calendar: z.string().min(1, "Calendar name is required").max(255),
  username: z.string().max(200),
  password: z.string().max(500),
});

type CalendarFormValues = z.infer<typeof calendarSchema>;

interface CalDavConfigFormProps {
  /** Called after a successful save (e.g. to close the parent dialog). */
  onSaved: () => void;
}

/** CalDAV connection form: URL, calendar name, credentials, save, and test. */
export function CalDavConfigForm({ onSaved }: CalDavConfigFormProps) {
  const { toast } = useToast();
  const queryClient = useQueryClient();

  const configQuery = useGetConfigApiCalendarConfigGet();
  const config = unwrapResponse<CalDAVConfigResponse | null>(configQuery.data);

  const updateMutation = useUpdateConfigApiCalendarConfigPut();
  const testMutation = useTestConfigApiCalendarConfigTestPost();

  const {
    register,
    handleSubmit,
    reset,
    getValues,
    setValue,
    formState: { errors },
  } = useForm<CalendarFormValues>({
    resolver: zodResolver(calendarSchema),
    defaultValues: {
      caldav_url: "",
      default_calendar: "",
      username: "",
      password: "",
    },
  });

  useEffect(() => {
    if (config) {
      reset({
        caldav_url: config.caldav_url ?? "",
        default_calendar: config.default_calendar ?? "",
        username: "",
        password: "",
      });
    }
  }, [config, reset]);

  async function onSave(data: CalendarFormValues) {
    try {
      await updateMutation.mutateAsync({
        data: {
          caldav_url: data.caldav_url,
          default_calendar: data.default_calendar,
          username: data.username,
          password: data.password,
        },
      });
      queryClient.invalidateQueries({
        queryKey: getGetConfigApiCalendarConfigGetQueryKey(),
      });
      toast({
        title: "Calendar configuration saved",
        description: "Your CalDAV settings have been updated.",
      });
      onSaved();
    } catch {
      toast({
        title: "Failed to save configuration",
        description: "Could not save the calendar settings. Please try again.",
        variant: "destructive",
      });
    }
  }

  async function onTest() {
    const values = getValues();
    const hasCredentials = values.caldav_url && values.username && values.password;
    if (!hasCredentials && !config) {
      toast({
        title: "Validation error",
        description: "URL, username, and password are required for testing.",
        variant: "destructive",
      });
      return;
    }

    try {
      const res = await testMutation.mutateAsync({
        data: {
          caldav_url: values.caldav_url || undefined,
          username: values.username || undefined,
          password: values.password || undefined,
          default_calendar: values.default_calendar || "",
        },
      });
      const result = unwrapResponse<CalDAVTestResponse>(res);
      if (result?.success) {
        const details = result.details ?? {};

        // Auto-fill discovered CalDAV URL if different.
        const discoveredUrl = details.caldav_url as string | undefined;
        if (discoveredUrl && discoveredUrl !== values.caldav_url) {
          setValue("caldav_url", discoveredUrl);
        }

        // Auto-fill first non-birthday calendar if the field is empty.
        const calSlugs = (details.calendar_slugs as string[]) ?? [];
        const calNames = result.calendars ?? [];
        if (!values.default_calendar && calNames.length > 0) {
          const idx = calSlugs.findIndex(
            (s) => !s.includes("birthday") && !s.includes("geburtstag"),
          );
          const pick = (idx >= 0 ? calNames[idx] : calNames[0]) ?? "";
          setValue("default_calendar", pick);
        }

        const calList =
          calNames.length > 0
            ? calNames.map((name, i) => `${name} (${calSlugs[i] ?? name})`).join(", ")
            : "";
        toast({
          title: "Connection successful",
          description: calList
            ? `${result.message}\n\nCalendars: ${calList}`
            : result.message,
        });
      } else {
        toast({
          title: "Connection failed",
          description: result?.message ?? "Unknown error",
          variant: "destructive",
        });
      }
    } catch {
      toast({
        title: "Connection test failed",
        description:
          "Could not reach the CalDAV server. Please check your credentials.",
        variant: "destructive",
      });
    }
  }

  if (configQuery.isError) {
    return (
      <QueryError
        message="Failed to load calendar configuration."
        onRetry={() => configQuery.refetch()}
      />
    );
  }

  if (configQuery.isLoading) {
    return (
      <div className="space-y-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="space-y-2">
            <Skeleton className="h-4 w-24" />
            <Skeleton className="h-10 w-full" />
          </div>
        ))}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <form onSubmit={handleSubmit(onSave)} className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="caldav_url">CalDAV URL</Label>
          <Input
            id="caldav_url"
            placeholder="https://nextcloud.example.com"
            {...register("caldav_url")}
          />
          {errors.caldav_url ? (
            <p className="text-xs text-destructive">{errors.caldav_url.message}</p>
          ) : (
            <p className="text-xs text-muted-foreground">
              Just the server URL is enough — the full DAV path is auto-detected.
            </p>
          )}
        </div>

        <div className="space-y-2">
          <Label htmlFor="default_calendar">Calendar Name</Label>
          <Input
            id="default_calendar"
            placeholder="Personal"
            {...register("default_calendar")}
          />
          {errors.default_calendar ? (
            <p className="text-xs text-destructive">{errors.default_calendar.message}</p>
          ) : (
            <p className="text-xs text-muted-foreground">
              Auto-filled by &quot;Test Connection&quot;. Leave empty to discover available
              calendars.
            </p>
          )}
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor="cal-username">Username</Label>
            <Input
              id="cal-username"
              placeholder="user@example.com"
              {...register("username")}
              autoComplete="off"
            />
            {errors.username && (
              <p className="text-xs text-destructive">{errors.username.message}</p>
            )}
          </div>
          <div className="space-y-2">
            <Label htmlFor="cal-password">Password</Label>
            <Input
              id="cal-password"
              type="password"
              placeholder={config ? "Enter new password to change" : "Password"}
              {...register("password")}
              autoComplete="off"
            />
            {errors.password && (
              <p className="text-xs text-destructive">{errors.password.message}</p>
            )}
            {config && (
              <p className="text-xs text-muted-foreground">
                Leave blank to keep the existing password.
              </p>
            )}
          </div>
        </div>

        <Separator />

        <div className="flex flex-wrap gap-2">
          <AppButton
            type="submit"
            icon={<Save />}
            label="Save Configuration"
            variant="primary"
            disabled={updateMutation.isPending}
            loading={updateMutation.isPending}
          >
            Save Configuration
          </AppButton>
          <AppButton
            type="button"
            icon={<FlaskConical />}
            label="Test Connection"
            onClick={onTest}
            disabled={testMutation.isPending}
            loading={testMutation.isPending}
          >
            Test Connection
          </AppButton>
        </div>
      </form>
    </div>
  );
}

import {
  Pencil,
  Trash2,
  FlaskConical,
  ChevronRight,
  Hash,
  Clock,
} from "lucide-react";

import type { RuleResponse, ConditionGroup } from "@/types/api";

import { AppButton } from "@/components/app-button";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import { Card, CardContent } from "@/components/ui/card";
import { cn, formatRelativeTime } from "@/lib/utils";

import { summarizeConditions, summarizeActions } from "./rules-constants";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface RuleCardProps {
  rule: RuleResponse;
  index: number;
  totalCount: number;
  isReordering: boolean;
  onMoveUp: (index: number) => void;
  onMoveDown: (index: number) => void;
  onToggleActive: (rule: RuleResponse) => void;
  onEdit: (rule: RuleResponse) => void;
  onTest: (ruleId: string) => void;
  onDelete: (ruleId: string) => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function RuleCard({
  rule,
  index,
  totalCount,
  isReordering,
  onMoveUp,
  onMoveDown,
  onToggleActive,
  onEdit,
  onTest,
  onDelete,
}: RuleCardProps) {
  return (
    <Card className={cn(!rule.is_active && "opacity-60")}>
      <CardContent className="flex items-start gap-3 py-3">
        {/* Drag handle + priority */}
        <div className="flex flex-col items-center gap-0.5 pt-1">
          <AppButton
            icon={<ChevronRight className="-rotate-90" />}
            label="Move rule up"
            variant="ghost"
            className="h-5 w-5"
            onClick={() => onMoveUp(index)}
            disabled={index === 0 || isReordering}
          />
          <div className="flex h-6 w-6 items-center justify-center rounded bg-muted text-[10px] font-bold">
            {rule.priority}
          </div>
          <AppButton
            icon={<ChevronRight className="rotate-90" />}
            label="Move rule down"
            variant="ghost"
            className="h-5 w-5"
            onClick={() => onMoveDown(index)}
            disabled={index === totalCount - 1 || isReordering}
          />
        </div>

        {/* Content */}
        <div className="min-w-0 flex-1 space-y-1.5">
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-semibold truncate">{rule.name}</h3>
            {!rule.is_active && (
              <Badge variant="secondary">
                Inactive
              </Badge>
            )}
            {rule.stop_processing && (
              <Badge variant="secondary">
                Stop
              </Badge>
            )}
          </div>
          {rule.description && (
            <p className="text-xs text-muted-foreground truncate">
              {rule.description}
            </p>
          )}
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
            <span className="truncate max-w-[300px]" title={summarizeConditions(rule.conditions as unknown as ConditionGroup)}>
              <span className="font-medium text-foreground/70">If:</span>{" "}
              {summarizeConditions(rule.conditions as unknown as ConditionGroup)}
            </span>
            <span className="truncate max-w-[250px]" title={summarizeActions(rule.actions as Array<Record<string, unknown>>)}>
              <span className="font-medium text-foreground/70">Then:</span>{" "}
              {summarizeActions(rule.actions as Array<Record<string, unknown>>)}
            </span>
          </div>
          <div className="flex items-center gap-4 text-[11px] text-muted-foreground">
            <span className="flex items-center gap-1">
              <Hash className="h-3 w-3" />
              {rule.match_count} matches
            </span>
            {rule.last_matched_at && (
              <span className="flex items-center gap-1">
                <Clock className="h-3 w-3" />
                Last: {formatRelativeTime(rule.last_matched_at)}
              </span>
            )}
          </div>
        </div>

        {/* Actions */}
        <div className="flex shrink-0 items-center gap-2">
          <Switch
            checked={rule.is_active}
            onCheckedChange={() => onToggleActive(rule)}
          />
          <AppButton icon={<Pencil />} label="Edit rule" variant="ghost" onClick={() => onEdit(rule)} />
          <AppButton icon={<FlaskConical />} label="Test rule" variant="ghost" onClick={() => onTest(rule.id)} />
          <AppButton icon={<Trash2 />} label="Delete rule" variant="ghost" color="destructive" onClick={() => onDelete(rule.id)} />
        </div>
      </CardContent>
    </Card>
  );
}

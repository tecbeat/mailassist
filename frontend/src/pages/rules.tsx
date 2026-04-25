import { useState } from "react";
import { usePageTitle } from "@/hooks/use-page-title";
import {
  Plus,
  Wand2,
  Pencil,
  Trash2,
  FlaskConical,
  ChevronRight,
  X,
  Save,
  Check,
  XCircle,
  AlertCircle,
  Clock,
  Hash,
} from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod/v4";

import {
  useListRulesApiRulesGet,
  useCreateRuleApiRulesPost,
  useUpdateRuleApiRulesRuleIdPut,
  useDeleteRuleApiRulesRuleIdDelete,
  useReorderRulesApiRulesReorderPut,
  useTestRuleApiRulesRuleIdTestPost,
  getListRulesApiRulesGetQueryKey,
} from "@/services/api/rules/rules";
import {
  useNlToRuleApiRulesFromNaturalLanguagePost,
} from "@/services/api/rules/rules";
import type {
  RuleResponse,
  RuleCreate,
  RuleUpdate,
  RuleAction,
  ConditionGroup,
  ConditionRule,
  TestMailInput,
  TestRuleResult,
  NLRuleResponse,
  RuleListResponse,
} from "@/types/api";
import { ConditionOperator, FieldOperator, ActionType } from "@/types/api";

import { PageHeader } from "@/components/layout/page-header";
import { QueryError } from "@/components/query-error";
import { AppButton } from "@/components/app-button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
import { Skeleton } from "@/components/ui/skeleton";
import { Separator } from "@/components/ui/separator";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { DeleteConfirmDialog } from "@/components/delete-confirm-dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useToast } from "@/components/ui/toast";
import { cn, formatRelativeTime, unwrapResponse } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const FIELD_OPTIONS = [
  { value: "from", label: "From" },
  { value: "to", label: "To" },
  { value: "cc", label: "CC" },
  { value: "subject", label: "Subject" },
  { value: "body", label: "Body" },
  { value: "has_attachments", label: "Has Attachments" },
  { value: "is_reply", label: "Is Reply" },
  { value: "is_forwarded", label: "Is Forwarded" },
  { value: "attachment_name", label: "Attachment Name" },
  { value: "contact_name", label: "Contact Name" },
  { value: "contact_org", label: "Contact Org" },
  { value: "header:X-Mailer", label: "Header: X-Mailer" },
  { value: "header:X-Spam-Score", label: "Header: X-Spam-Score" },
  { value: "header:List-Unsubscribe", label: "Header: List-Unsubscribe" },
] as const;

const OPERATOR_OPTIONS = Object.values(FieldOperator).map((op) => ({
  value: op,
  label: op.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()),
}));

const OPERATORS_WITHOUT_VALUE: string[] = [FieldOperator.is_empty, FieldOperator.is_not_empty];

const ACTION_TYPE_OPTIONS = Object.values(ActionType).map((t) => ({
  value: t,
  label: t.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()),
}));

const ACTIONS_NEEDING_VALUE: ActionType[] = [
  ActionType.label,
  ActionType.remove_label,
  ActionType.flag,
];

const ACTIONS_NEEDING_TARGET: ActionType[] = [
  ActionType.move,
  ActionType.copy,
  ActionType.notify,
  ActionType.create_draft,
];

const MAX_NESTING_DEPTH = 5;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function isConditionGroup(rule: ConditionRule | ConditionGroup): rule is ConditionGroup {
  return "operator" in rule && "rules" in rule;
}

function createEmptyConditionRule(): ConditionRule {
  return { field: "from", op: FieldOperator.contains, value: "" };
}

function createEmptyConditionGroup(): ConditionGroup {
  return { operator: ConditionOperator.AND, rules: [createEmptyConditionRule()] };
}

function createEmptyAction(): RuleAction {
  return { type: ActionType.label, value: "", target: null };
}

function summarizeConditions(group: ConditionGroup | Record<string, unknown>, depth = 0): string {
  if (depth > 3) return "...";
  const g = group as ConditionGroup;
  if (!g.rules?.length) return "(empty)";

  const parts = g.rules.map((r) => {
    if (isConditionGroup(r as ConditionRule | ConditionGroup)) {
      return `(${summarizeConditions(r as ConditionGroup, depth + 1)})`;
    }
    const cr = r as ConditionRule;
    const op = String(cr.op).replace(/_/g, " ");
    if (OPERATORS_WITHOUT_VALUE.includes(cr.op)) {
      return `${cr.field} ${op}`;
    }
    return `${cr.field} ${op} "${cr.value ?? ""}"`;
  });

  return parts.join(` ${g.operator} `);
}

function summarizeActions(actions: Array<Record<string, unknown> | RuleAction>): string {
  return actions
    .map((a) => {
      const label = String(a.type ?? "").replace(/_/g, " ");
      if (a.value) return `${label}: ${a.value}`;
      if (a.target) return `${label} -> ${a.target}`;
      return label;
    })
    .join(", ");
}

/** Validate that conditions have required values filled in. */
function isConditionGroupValid(group: ConditionGroup): boolean {
  if (!group.rules?.length) return false;
  return group.rules.every((rule) => {
    if (isConditionGroup(rule as ConditionRule | ConditionGroup)) {
      return isConditionGroupValid(rule as ConditionGroup);
    }
    const cr = rule as ConditionRule;
    if (!cr.field || !cr.op) return false;
    // Operators like is_empty / is_not_empty don't need a value
    if (OPERATORS_WITHOUT_VALUE.includes(cr.op)) return true;
    return typeof cr.value === "string" ? cr.value.trim().length > 0 : cr.value != null;
  });
}

/** Validate that all actions have required fields filled in. */
function areActionsValid(actions: RuleAction[]): boolean {
  if (!actions.length) return false;
  return actions.every((action) => {
    if (!action.type) return false;
    if (ACTIONS_NEEDING_VALUE.includes(action.type as ActionType)) {
      return typeof action.value === "string" && action.value.trim().length > 0;
    }
    if (ACTIONS_NEEDING_TARGET.includes(action.type as ActionType)) {
      return typeof action.target === "string" && action.target.trim().length > 0;
    }
    return true;
  });
}

// ---------------------------------------------------------------------------
// Condition builder (recursive)
// ---------------------------------------------------------------------------

interface ConditionBuilderProps {
  group: ConditionGroup;
  onChange: (group: ConditionGroup) => void;
  depth?: number;
}

function ConditionBuilder({ group, onChange, depth = 0 }: ConditionBuilderProps) {
  const updateOperator = (op: string) => {
    onChange({ ...group, operator: op as ConditionGroup["operator"] });
  };

  const updateRule = (index: number, updated: ConditionRule | ConditionGroup) => {
    const newRules = [...group.rules];
    newRules[index] = updated;
    onChange({ ...group, rules: newRules });
  };

  const addRule = () => {
    onChange({ ...group, rules: [...group.rules, createEmptyConditionRule()] });
  };

  const addGroup = () => {
    if (depth >= MAX_NESTING_DEPTH - 1) return;
    onChange({ ...group, rules: [...group.rules, createEmptyConditionGroup()] });
  };

  const removeRule = (index: number) => {
    if (group.rules.length <= 1) return;
    const newRules = group.rules.filter((_, i) => i !== index);
    onChange({ ...group, rules: newRules });
  };

  return (
    <div
      className={cn(
        "rounded-md border border-border p-3 space-y-2",
        depth > 0 && "ml-4 border-dashed",
      )}
    >
      {/* Group header */}
      <div className="flex items-center gap-2">
        <Select value={group.operator} onValueChange={updateOperator}>
          <SelectTrigger className="w-20 h-7 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ConditionOperator.AND}>AND</SelectItem>
            <SelectItem value={ConditionOperator.OR}>OR</SelectItem>
          </SelectContent>
        </Select>
        <span className="text-xs text-muted-foreground">
          {group.operator === ConditionOperator.AND
            ? "All conditions must match"
            : "Any condition must match"}
        </span>
      </div>

      {/* Rules */}
      {group.rules.map((rule, index) => {
        const isGroup = isConditionGroup(rule as ConditionRule | ConditionGroup);
        return (
          <div key={index} className="relative">
            {isGroup ? (
              <div className="flex items-start gap-1">
                <div className="flex-1">
                  <ConditionBuilder
                    group={rule as ConditionGroup}
                    onChange={(updated) => updateRule(index, updated)}
                    depth={depth + 1}
                  />
                </div>
                <AppButton
                  icon={<X />}
                  label="Remove condition group"
                  variant="ghost"
                  color="destructive"
                  className="h-7 w-7 shrink-0"
                  onClick={() => removeRule(index)}
                  disabled={group.rules.length <= 1}
                />
              </div>
            ) : (
              <ConditionRuleRow
                rule={rule as ConditionRule}
                onChange={(updated) => updateRule(index, updated)}
                onRemove={() => removeRule(index)}
                canRemove={group.rules.length > 1}
              />
            )}
          </div>
        );
      })}

      {/* Add buttons */}
      <div className="flex gap-2 pt-1">
        <AppButton icon={<Plus />} label="Add condition" className="h-7 text-xs" type="button" onClick={addRule}>Condition</AppButton>
        {depth < MAX_NESTING_DEPTH - 1 && (
          <AppButton icon={<Plus />} label="Add condition group" className="h-7 text-xs" type="button" onClick={addGroup}>Group</AppButton>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Single condition rule row
// ---------------------------------------------------------------------------

interface ConditionRuleRowProps {
  rule: ConditionRule;
  onChange: (rule: ConditionRule) => void;
  onRemove: () => void;
  canRemove: boolean;
}

function ConditionRuleRow({ rule, onChange, onRemove, canRemove }: ConditionRuleRowProps) {
  const needsValue = !OPERATORS_WITHOUT_VALUE.includes(rule.op);

  return (
    <div className="flex items-center gap-2">
      <Select value={rule.field} onValueChange={(v) => onChange({ ...rule, field: v })}>
        <SelectTrigger className="h-7 w-[140px] text-xs">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {FIELD_OPTIONS.map((f) => (
            <SelectItem key={f.value} value={f.value}>
              {f.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      <Select value={rule.op} onValueChange={(v) => onChange({ ...rule, op: v as ConditionRule["op"] })}>
        <SelectTrigger className="h-7 w-[130px] text-xs">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {OPERATOR_OPTIONS.map((o) => (
            <SelectItem key={o.value} value={o.value}>
              {o.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      {needsValue && (
        <Input
          value={String(rule.value ?? "")}
          onChange={(e) => onChange({ ...rule, value: e.target.value })}
          className="h-7 flex-1 text-xs"
          placeholder="Value..."
        />
      )}

      <AppButton
        icon={<X />}
        label="Remove condition"
        variant="ghost"
        color="destructive"
        className="h-7 w-7 shrink-0"
        onClick={onRemove}
        disabled={!canRemove}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Actions editor
// ---------------------------------------------------------------------------

interface ActionsEditorProps {
  actions: RuleAction[];
  onChange: (actions: RuleAction[]) => void;
}

function ActionsEditor({ actions, onChange }: ActionsEditorProps) {
  const updateAction = (index: number, updated: RuleAction) => {
    const newActions = [...actions];
    newActions[index] = updated;
    onChange(newActions);
  };

  const addAction = () => {
    onChange([...actions, createEmptyAction()]);
  };

  const removeAction = (index: number) => {
    if (actions.length <= 1) return;
    onChange(actions.filter((_, i) => i !== index));
  };

  return (
    <div className="space-y-2">
      {actions.map((action, index) => (
        <div key={index} className="flex items-center gap-2">
          <Select
            value={action.type}
            onValueChange={(v) =>
              updateAction(index, { ...action, type: v as RuleAction["type"] })
            }
          >
            <SelectTrigger className="h-8 w-[160px] text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {ACTION_TYPE_OPTIONS.map((t) => (
                <SelectItem key={t.value} value={t.value}>
                  {t.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          {ACTIONS_NEEDING_VALUE.includes(action.type as ActionType) && (
            <Input
              value={action.value ?? ""}
              onChange={(e) => updateAction(index, { ...action, value: e.target.value })}
              className="h-8 flex-1 text-xs"
              placeholder="Value (e.g. label name)..."
            />
          )}

          {ACTIONS_NEEDING_TARGET.includes(action.type as ActionType) && (
            <Input
              value={action.target ?? ""}
              onChange={(e) => updateAction(index, { ...action, target: e.target.value })}
              className="h-8 flex-1 text-xs"
              placeholder="Target (e.g. folder path)..."
            />
          )}

          <AppButton
            icon={<X />}
            label="Remove action"
            variant="ghost"
            color="destructive"
            className="h-7 w-7 shrink-0"
            onClick={() => removeAction(index)}
            disabled={actions.length <= 1}
          />
        </div>
      ))}

      <AppButton icon={<Plus />} label="Add action" className="h-7 text-xs" type="button" onClick={addAction}>Action</AppButton>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Rule form schema (top-level fields validated by zod)
// ---------------------------------------------------------------------------

const ruleFormSchema = z.object({
  name: z.string().trim().min(1, "Name is required"),
  description: z.string(),
  priority: z.number().int().min(0, "Priority must be non-negative"),
  is_active: z.boolean(),
  stop_processing: z.boolean(),
});

type RuleFormValues = z.infer<typeof ruleFormSchema>;

function emptyFormDefaults(priority = 0): RuleFormValues {
  return { name: "", description: "", priority, is_active: true, stop_processing: false };
}

function ruleToFormValues(rule: RuleResponse): RuleFormValues {
  return {
    name: rule.name,
    description: rule.description ?? "",
    priority: rule.priority,
    is_active: rule.is_active,
    stop_processing: rule.stop_processing,
  };
}

function ruleToConditions(rule: RuleResponse): ConditionGroup {
  const conditions = rule.conditions as unknown as ConditionGroup;
  return conditions?.operator ? conditions : createEmptyConditionGroup();
}

function ruleToActions(rule: RuleResponse): RuleAction[] {
  const actions = rule.actions as unknown as RuleAction[];
  return actions?.length ? actions : [createEmptyAction()];
}

function nlResponseToFormValues(nl: NLRuleResponse): RuleFormValues {
  return {
    name: nl.name,
    description: nl.description ?? "",
    priority: 0,
    is_active: true,
    stop_processing: nl.stop_processing ?? false,
  };
}

function nlResponseToConditions(nl: NLRuleResponse): ConditionGroup {
  const conditions = nl.conditions as unknown as ConditionGroup;
  return conditions?.operator ? conditions : createEmptyConditionGroup();
}

function nlResponseToActions(nl: NLRuleResponse): RuleAction[] {
  const actions = nl.actions as unknown as RuleAction[];
  return actions?.length ? actions : [createEmptyAction()];
}

// ---------------------------------------------------------------------------
// Main page component
// ---------------------------------------------------------------------------

export default function RulesPage() {
  usePageTitle("Rules");
  const { toast } = useToast();
  const queryClient = useQueryClient();

  // --- State ---
  const [editDialogOpen, setEditDialogOpen] = useState(false);
  const [editingRuleId, setEditingRuleId] = useState<string | null>(null);

  // Top-level fields managed by react-hook-form + zod
  const ruleForm = useForm<RuleFormValues>({
    resolver: zodResolver(ruleFormSchema),
    defaultValues: emptyFormDefaults(),
  });

  // Conditions and actions are recursive/dynamic — kept as separate state
  const [conditions, setConditions] = useState<ConditionGroup>(createEmptyConditionGroup());
  const [actions, setActions] = useState<RuleAction[]>([createEmptyAction()]);

  const [deleteId, setDeleteId] = useState<string | null>(null);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);

  const [testDialogOpen, setTestDialogOpen] = useState(false);
  const [testRuleId, setTestRuleId] = useState<string | null>(null);
  const [testInput, setTestInput] = useState<TestMailInput>({
    sender: "",
    subject: "",
    body: "",
  });
  const [testResult, setTestResult] = useState<TestRuleResult | null>(null);

  const [nlDialogOpen, setNlDialogOpen] = useState(false);
  const [nlDescription, setNlDescription] = useState("");
  const [nlResult, setNlResult] = useState<NLRuleResponse | null>(null);

  // --- Data fetching ---
  const rulesQuery = useListRulesApiRulesGet();
  const rulesData = unwrapResponse<RuleListResponse>(rulesQuery.data);
  const rules = rulesData?.items ?? [];

  // --- Mutations ---
  const createMutation = useCreateRuleApiRulesPost();
  const updateMutation = useUpdateRuleApiRulesRuleIdPut();
  const deleteMutation = useDeleteRuleApiRulesRuleIdDelete();
  const reorderMutation = useReorderRulesApiRulesReorderPut();
  const testMutation = useTestRuleApiRulesRuleIdTestPost();
  const nlMutation = useNlToRuleApiRulesFromNaturalLanguagePost();

  const invalidateRules = () => {
    queryClient.invalidateQueries({ queryKey: getListRulesApiRulesGetQueryKey() });
  };

  // --- Edit/Add dialog ---
  const openAddDialog = () => {
    setEditingRuleId(null);
    const priority = rules.length > 0 ? Math.max(...rules.map((r) => r.priority)) + 10 : 10;
    ruleForm.reset(emptyFormDefaults(priority));
    setConditions(createEmptyConditionGroup());
    setActions([createEmptyAction()]);
    setEditDialogOpen(true);
  };

  const openEditDialog = (rule: RuleResponse) => {
    setEditingRuleId(rule.id);
    ruleForm.reset(ruleToFormValues(rule));
    setConditions(ruleToConditions(rule));
    setActions(ruleToActions(rule));
    setEditDialogOpen(true);
  };

  const handleSaveRule = ruleForm.handleSubmit((values) => {
    const payload = {
      name: values.name,
      description: values.description || null,
      priority: values.priority,
      is_active: values.is_active,
      conditions,
      actions,
      stop_processing: values.stop_processing,
    };

    if (editingRuleId) {
      updateMutation.mutate(
        { ruleId: editingRuleId, data: payload as RuleUpdate },
        {
          onSuccess: () => {
            toast({ title: "Rule updated", description: `"${values.name}" saved successfully.` });
            setEditDialogOpen(false);
            invalidateRules();
          },
          onError: () => {
            toast({ title: "Update failed", description: "Could not update rule.", variant: "destructive" });
          },
        },
      );
    } else {
      createMutation.mutate(
        { data: payload as RuleCreate },
        {
          onSuccess: () => {
            toast({ title: "Rule created", description: `"${values.name}" created successfully.` });
            setEditDialogOpen(false);
            invalidateRules();
          },
          onError: () => {
            toast({ title: "Create failed", description: "Could not create rule.", variant: "destructive" });
          },
        },
      );
    }
  });

  // --- Delete ---
  const openDeleteDialog = (ruleId: string) => {
    setDeleteId(ruleId);
    setDeleteDialogOpen(true);
  };

  const handleDelete = () => {
    if (!deleteId) return;
    deleteMutation.mutate(
      { ruleId: deleteId },
      {
        onSuccess: () => {
          toast({ title: "Rule deleted", description: "Rule has been removed." });
          setDeleteDialogOpen(false);
          setDeleteId(null);
          invalidateRules();
        },
        onError: () => {
          toast({ title: "Delete failed", description: "Could not delete rule.", variant: "destructive" });
        },
      },
    );
  };

  // --- Active toggle ---
  const handleToggleActive = (rule: RuleResponse) => {
    updateMutation.mutate(
      { ruleId: rule.id, data: { is_active: !rule.is_active } },
      {
        onSuccess: () => {
          toast({
            title: rule.is_active ? "Rule deactivated" : "Rule activated",
            description: `"${rule.name}" is now ${rule.is_active ? "inactive" : "active"}.`,
          });
          invalidateRules();
        },
        onError: () => {
          toast({ title: "Toggle failed", variant: "destructive" });
        },
      },
    );
  };

  // --- Reorder (move up/down) ---
  const handleMoveUp = (index: number) => {
    if (index <= 0) return;
    const sorted = [...rules].sort((a, b) => a.priority - b.priority);
    const prev = sorted[index - 1];
    const curr = sorted[index];
    if (!prev || !curr) return;
    const reordered = sorted.map((rule, i) => ({
      id: rule.id,
      priority: i === index ? prev.priority : i === index - 1 ? curr.priority : rule.priority,
    }));
    reorderMutation.mutate(
      { data: { rules: reordered } },
      {
        onSuccess: invalidateRules,
        onError: () => {
          toast({
            title: "Error",
            description: "Failed to reorder rules. Please try again.",
            variant: "destructive",
          });
        },
      },
    );
  };

  const handleMoveDown = (index: number) => {
    const sorted = [...rules].sort((a, b) => a.priority - b.priority);
    if (index >= sorted.length - 1) return;
    const curr = sorted[index];
    const next = sorted[index + 1];
    if (!curr || !next) return;
    const reordered = sorted.map((rule, i) => ({
      id: rule.id,
      priority: i === index ? next.priority : i === index + 1 ? curr.priority : rule.priority,
    }));
    reorderMutation.mutate(
      { data: { rules: reordered } },
      {
        onSuccess: invalidateRules,
        onError: () => {
          toast({
            title: "Error",
            description: "Failed to reorder rules. Please try again.",
            variant: "destructive",
          });
        },
      },
    );
  };

  // --- Test ---
  const openTestDialog = (ruleId: string) => {
    setTestRuleId(ruleId);
    setTestResult(null);
    setTestInput({ sender: "", subject: "", body: "" });
    setTestDialogOpen(true);
  };

  const handleTest = () => {
    if (!testRuleId) return;
    testMutation.mutate(
      { ruleId: testRuleId, data: testInput },
      {
        onSuccess: (res) => {
          const result = unwrapResponse<TestRuleResult>(res);
          if (result) setTestResult(result);
        },
        onError: () => {
          toast({ title: "Test failed", description: "Could not test rule.", variant: "destructive" });
        },
      },
    );
  };

  // --- Natural Language ---
  const handleNlGenerate = () => {
    if (!nlDescription.trim()) return;
    nlMutation.mutate(
      { data: { description: nlDescription } },
      {
        onSuccess: (res) => {
          const result = unwrapResponse<NLRuleResponse>(res);
          if (result) setNlResult(result);
        },
        onError: () => {
          toast({ title: "Generation failed", description: "Could not generate rule from description.", variant: "destructive" });
        },
      },
    );
  };

  const handleNlConfirm = () => {
    if (!nlResult) return;
    const values = nlResponseToFormValues(nlResult);
    values.priority = rules.length > 0 ? Math.max(...rules.map((r) => r.priority)) + 10 : 10;
    setEditingRuleId(null);
    ruleForm.reset(values);
    setConditions(nlResponseToConditions(nlResult));
    setActions(nlResponseToActions(nlResult));
    setNlDialogOpen(false);
    setNlResult(null);
    setNlDescription("");
    setEditDialogOpen(true);
  };

  // --- Sorted rules ---
  const sortedRules = [...rules].sort((a, b) => a.priority - b.priority);

  const isSaving = createMutation.isPending || updateMutation.isPending;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Rules"
        description="Define conditions and actions to process emails automatically."
        actions={
          <>
            <AppButton icon={<Wand2 />} label="Natural Language" onClick={() => { setNlDescription(""); setNlResult(null); setNlDialogOpen(true); }}>Natural Language</AppButton>
            <AppButton icon={<Plus />} label="Add Rule" variant="primary" onClick={openAddDialog}>Add Rule</AppButton>
          </>
        }
      />

      {/* ---------------------------------------------------------------- */}
      {/* Rules list                                                       */}
      {/* ---------------------------------------------------------------- */}
      {rulesQuery.isError ? (
        <QueryError message="Failed to load rules." onRetry={() => rulesQuery.refetch()} />
      ) : rulesQuery.isLoading ? (
        <div className="space-y-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Card key={i}>
              <CardContent className="flex items-center gap-4 py-4">
                <Skeleton className="h-10 w-10 rounded" />
                <div className="flex-1 space-y-2">
                  <Skeleton className="h-4 w-48" />
                  <Skeleton className="h-3 w-96" />
                </div>
                <Skeleton className="h-8 w-20" />
              </CardContent>
            </Card>
          ))}
        </div>
      ) : sortedRules.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-12 text-center">
            <AlertCircle className="mb-3 h-10 w-10 text-muted-foreground/50" />
            <h3 className="text-lg font-medium">No rules configured</h3>
            <p className="mt-1 max-w-sm text-sm text-muted-foreground">
              Create rules to automatically process emails based on conditions like sender, subject, or content.
            </p>
            <div className="mt-4 flex gap-2">
              <AppButton icon={<Wand2 />} label="Natural Language" onClick={() => { setNlDescription(""); setNlResult(null); setNlDialogOpen(true); }}>From Natural Language</AppButton>
              <AppButton icon={<Plus />} label="Add Rule" variant="primary" onClick={openAddDialog}>Add Rule</AppButton>
            </div>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-2">
          {sortedRules.map((rule, index) => (
            <Card
              key={rule.id}
              className={cn(!rule.is_active && "opacity-60")}
            >
              <CardContent className="flex items-start gap-3 py-3">
                {/* Drag handle + priority */}
                <div className="flex flex-col items-center gap-0.5 pt-1">
                  <AppButton
                    icon={<ChevronRight className="-rotate-90" />}
                    label="Move rule up"
                    variant="ghost"
                    className="h-5 w-5"
                    onClick={() => handleMoveUp(index)}
                    disabled={index === 0 || reorderMutation.isPending}
                  />
                  <div className="flex h-6 w-6 items-center justify-center rounded bg-muted text-[10px] font-bold">
                    {rule.priority}
                  </div>
                  <AppButton
                    icon={<ChevronRight className="rotate-90" />}
                    label="Move rule down"
                    variant="ghost"
                    className="h-5 w-5"
                    onClick={() => handleMoveDown(index)}
                    disabled={index === sortedRules.length - 1 || reorderMutation.isPending}
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
                    onCheckedChange={() => handleToggleActive(rule)}
                  />
                  <AppButton icon={<Pencil />} label="Edit rule" variant="ghost" onClick={() => openEditDialog(rule)} />
                  <AppButton icon={<FlaskConical />} label="Test rule" variant="ghost" onClick={() => openTestDialog(rule.id)} />
                  <AppButton icon={<Trash2 />} label="Delete rule" variant="ghost" color="destructive" onClick={() => openDeleteDialog(rule.id)} />
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* ---------------------------------------------------------------- */}
      {/* Add/Edit Rule Dialog                                             */}
      {/* ---------------------------------------------------------------- */}
      <Dialog open={editDialogOpen} onOpenChange={setEditDialogOpen}>
        <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{editingRuleId ? "Edit Rule" : "Add Rule"}</DialogTitle>
            <DialogDescription>
              {editingRuleId
                ? "Update rule conditions and actions."
                : "Define conditions to match emails and actions to execute."}
            </DialogDescription>
          </DialogHeader>

          <form id="rule-form" onSubmit={handleSaveRule} className="space-y-4">
            {/* Name & Description */}
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label className="text-xs">Name</Label>
                <Input
                  {...ruleForm.register("name")}
                  placeholder="Rule name..."
                />
                {ruleForm.formState.errors.name && (
                  <p className="text-xs text-destructive">{ruleForm.formState.errors.name.message}</p>
                )}
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs">Priority</Label>
                <Input
                  type="number"
                  min={0}
                  {...ruleForm.register("priority", { valueAsNumber: true })}
                />
                {ruleForm.formState.errors.priority && (
                  <p className="text-xs text-destructive">{ruleForm.formState.errors.priority.message}</p>
                )}
              </div>
            </div>

            <div className="space-y-1.5">
              <Label className="text-xs">Description (optional)</Label>
              <Input
                {...ruleForm.register("description")}
                placeholder="What this rule does..."
              />
            </div>

            {/* Conditions */}
            <div className="space-y-1.5">
              <Label className="text-xs font-semibold">Conditions</Label>
              <ConditionBuilder
                group={conditions}
                onChange={setConditions}
              />
            </div>

            <Separator />

            {/* Actions */}
            <div className="space-y-1.5">
              <Label className="text-xs font-semibold">Actions</Label>
              <ActionsEditor
                actions={actions}
                onChange={setActions}
              />
            </div>

            <Separator />

            {/* Options */}
            <div className="flex items-center justify-between">
              <div className="space-y-0.5">
                <Label className="text-xs">Stop Processing</Label>
                <p className="text-[11px] text-muted-foreground">
                  Skip remaining rules after this one matches.
                </p>
              </div>
              <Switch
                checked={ruleForm.watch("stop_processing")}
                onCheckedChange={(checked) => ruleForm.setValue("stop_processing", checked, { shouldDirty: true })}
              />
            </div>
          </form>

          <DialogFooter>
            <AppButton icon={<X />} label="Cancel" onClick={() => setEditDialogOpen(false)}>Cancel</AppButton>
            <AppButton icon={<Save />} label={editingRuleId ? "Update Rule" : "Create Rule"} type="submit" form="rule-form" variant="primary" loading={isSaving} disabled={isSaving || !isConditionGroupValid(conditions) || !areActionsValid(actions)}>{isSaving ? "Saving..." : editingRuleId ? "Update Rule" : "Create Rule"}</AppButton>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ---------------------------------------------------------------- */}
      {/* Delete Confirmation                                              */}
      {/* ---------------------------------------------------------------- */}
      <DeleteConfirmDialog
        open={deleteDialogOpen}
        onOpenChange={setDeleteDialogOpen}
        title="Delete rule?"
        description="This will permanently delete this rule. This action cannot be undone."
        onConfirm={handleDelete}
        isPending={deleteMutation.isPending}
      />

      {/* ---------------------------------------------------------------- */}
      {/* Test Rule Dialog                                                 */}
      {/* ---------------------------------------------------------------- */}
      <Dialog open={testDialogOpen} onOpenChange={setTestDialogOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>Test Rule</DialogTitle>
            <DialogDescription>
              Enter sample email data to test if this rule would match.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-3">
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label className="text-xs">Sender</Label>
                <Input
                  value={testInput.sender ?? ""}
                  onChange={(e) => setTestInput((s) => ({ ...s, sender: e.target.value }))}
                  placeholder="sender@example.com"
                />
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs">Recipient</Label>
                <Input
                  value={testInput.recipient ?? ""}
                  onChange={(e) => setTestInput((s) => ({ ...s, recipient: e.target.value }))}
                  placeholder="you@example.com"
                />
              </div>
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs">Subject</Label>
              <Input
                value={testInput.subject ?? ""}
                onChange={(e) => setTestInput((s) => ({ ...s, subject: e.target.value }))}
                placeholder="Email subject..."
              />
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs">Body</Label>
              <Textarea
                value={testInput.body ?? ""}
                onChange={(e) => setTestInput((s) => ({ ...s, body: e.target.value }))}
                placeholder="Email body..."
                className="min-h-[80px]"
              />
            </div>

            <div className="grid gap-3 sm:grid-cols-3">
              <div className="flex items-center gap-2">
                <Switch
                  id="test-attachments"
                  checked={testInput.has_attachments ?? false}
                  onCheckedChange={(checked) => setTestInput((s) => ({ ...s, has_attachments: checked }))}
                />
                <Label htmlFor="test-attachments" className="text-xs">
                  Has Attachments
                </Label>
              </div>
              <div className="flex items-center gap-2">
                <Switch
                  id="test-reply"
                  checked={testInput.is_reply ?? false}
                  onCheckedChange={(checked) => setTestInput((s) => ({ ...s, is_reply: checked }))}
                />
                <Label htmlFor="test-reply" className="text-xs">
                  Is Reply
                </Label>
              </div>
              <div className="flex items-center gap-2">
                <Switch
                  id="test-forwarded"
                  checked={testInput.is_forwarded ?? false}
                  onCheckedChange={(checked) => setTestInput((s) => ({ ...s, is_forwarded: checked }))}
                />
                <Label htmlFor="test-forwarded" className="text-xs">
                  Is Forwarded
                </Label>
              </div>
            </div>

            <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label className="text-xs">Contact Name</Label>
                <Input
                  value={testInput.contact_name ?? ""}
                  onChange={(e) => setTestInput((s) => ({ ...s, contact_name: e.target.value || null }))}
                  placeholder="John Doe"
                />
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs">Contact Org</Label>
                <Input
                  value={testInput.contact_org ?? ""}
                  onChange={(e) => setTestInput((s) => ({ ...s, contact_org: e.target.value || null }))}
                  placeholder="Acme Inc."
                />
              </div>
            </div>
          </div>

          {/* Test result */}
          {testResult && (
            <>
              <Separator />
              <div className="space-y-2">
                <div className="flex items-center gap-2">
                  {testResult.matched ? (
                    <>
                      <Check className="h-5 w-5 text-green-500" />
                      <span className="text-sm font-semibold text-green-600">Rule Matched</span>
                    </>
                  ) : (
                    <>
                      <XCircle className="h-5 w-5 text-red-500" />
                      <span className="text-sm font-semibold text-red-600">No Match</span>
                    </>
                  )}
                </div>

                {testResult.evaluation_details && (
                  <pre className="max-h-[200px] overflow-auto whitespace-pre-wrap rounded-md bg-muted p-3 text-xs">
                    {testResult.evaluation_details}
                  </pre>
                )}

                {testResult.matched && testResult.actions_that_would_execute.length > 0 && (
                  <div className="space-y-1">
                    <p className="text-xs font-medium">Actions that would execute:</p>
                    <div className="flex flex-wrap gap-1">
                      {testResult.actions_that_would_execute.map((action, i) => (
                        <Badge key={i} variant="secondary">
                          {summarizeActions([action as Record<string, unknown>])}
                        </Badge>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </>
          )}

          <DialogFooter>
            <AppButton icon={<X />} label="Close" onClick={() => setTestDialogOpen(false)}>Close</AppButton>
            <AppButton icon={<FlaskConical />} label="Run Test" variant="primary" loading={testMutation.isPending} disabled={testMutation.isPending} onClick={handleTest}>{testMutation.isPending ? "Testing..." : "Run Test"}</AppButton>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ---------------------------------------------------------------- */}
      {/* Natural Language Dialog                                          */}
      {/* ---------------------------------------------------------------- */}
      <Dialog open={nlDialogOpen} onOpenChange={setNlDialogOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>Create Rule from Natural Language</DialogTitle>
            <DialogDescription>
              Describe what you want in plain English and AI will generate a structured rule for you.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            <div className="space-y-1.5">
              <Label className="text-xs">Describe your rule</Label>
              <Textarea
                value={nlDescription}
                onChange={(e) => setNlDescription(e.target.value)}
                placeholder="e.g. Move all emails from newsletters@example.com to the Newsletters folder and mark them as read..."
                className="min-h-[100px]"
              />
            </div>

            <AppButton icon={<Wand2 />} label="Generate Rule" variant="primary" loading={nlMutation.isPending} disabled={nlMutation.isPending || !nlDescription.trim()} className="w-full" onClick={handleNlGenerate}>{nlMutation.isPending ? "Generating..." : "Generate Rule"}</AppButton>

            {/* NL result preview */}
            {nlResult && (
              <>
                <Separator />
                <Card>
                  <CardHeader className="pb-2">
                    <CardTitle className="text-sm">{nlResult.name}</CardTitle>
                    {nlResult.description && (
                      <CardDescription className="text-xs">
                        {nlResult.description}
                      </CardDescription>
                    )}
                  </CardHeader>
                  <CardContent className="space-y-2">
                    {nlResult.ai_reasoning && (
                      <div className="rounded-md bg-muted p-2 text-xs text-muted-foreground">
                        <span className="font-medium">AI reasoning:</span>{" "}
                        {nlResult.ai_reasoning}
                      </div>
                    )}
                    <div className="text-xs">
                      <span className="font-medium">Conditions:</span>{" "}
                      {summarizeConditions(nlResult.conditions as unknown as ConditionGroup)}
                    </div>
                    <div className="text-xs">
                      <span className="font-medium">Actions:</span>{" "}
                      {summarizeActions(nlResult.actions as Array<Record<string, unknown>>)}
                    </div>
                    {nlResult.stop_processing && (
                      <Badge variant="secondary">
                        Stop processing
                      </Badge>
                    )}
                  </CardContent>
                </Card>
              </>
            )}
          </div>

          {nlResult && (
            <DialogFooter>
              <AppButton icon={<X />} label="Cancel" onClick={() => setNlDialogOpen(false)}>Cancel</AppButton>
              <AppButton icon={<Check />} label="Edit & Save" variant="primary" onClick={handleNlConfirm}>Edit & Save</AppButton>
            </DialogFooter>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}

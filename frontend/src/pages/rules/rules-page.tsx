import { useState } from "react";
import { Plus, Wand2, AlertCircle } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";

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
  TestMailInput,
  TestRuleResult,
  NLRuleResponse,
  RuleListResponse,
} from "@/types/api";

import { PageHeader } from "@/components/layout/page-header";
import { QueryError } from "@/components/query-error";
import { AppButton } from "@/components/app-button";
import { Skeleton } from "@/components/ui/skeleton";
import { Card, CardContent } from "@/components/ui/card";
import { DeleteConfirmDialog } from "@/components/delete-confirm-dialog";
import { useToast } from "@/components/ui/toast";
import { unwrapResponse } from "@/lib/utils";

import {
  createEmptyConditionGroup,
  createEmptyAction,
} from "./rules-constants";
import {
  ruleFormSchema,
  type RuleFormValues,
  emptyFormDefaults,
  ruleToFormValues,
  ruleToConditions,
  ruleToActions,
  nlResponseToFormValues,
  nlResponseToConditions,
  nlResponseToActions,
} from "./rule-form-schema";
import { RuleCard } from "./rule-card";
import { RuleEditDialog } from "./rule-edit-dialog";
import { TestRuleDialog } from "./test-rule-dialog";
import { NlRuleDialog } from "./nl-rule-dialog";

// ---------------------------------------------------------------------------
// Main page component
// ---------------------------------------------------------------------------

export default function RulesPage() {
  const { toast } = useToast();
  const queryClient = useQueryClient();

  // --- State ---
  const [editDialogOpen, setEditDialogOpen] = useState(false);
  const [editingRuleId, setEditingRuleId] = useState<string | null>(null);

  const ruleForm = useForm<RuleFormValues>({
    resolver: zodResolver(ruleFormSchema),
    defaultValues: emptyFormDefaults(),
  });

  const [conditions, setConditions] = useState<ConditionGroup>(createEmptyConditionGroup());
  const [actions, setActions] = useState<RuleAction[]>([createEmptyAction()]);

  const [deleteId, setDeleteId] = useState<string | null>(null);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);

  const [testDialogOpen, setTestDialogOpen] = useState(false);
  const [testRuleId, setTestRuleId] = useState<string | null>(null);
  const [testInput, setTestInput] = useState<TestMailInput>({ sender: "", subject: "", body: "" });
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

  // --- Reorder ---
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

      {/* Rules list */}
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
            <RuleCard
              key={rule.id}
              rule={rule}
              index={index}
              totalCount={sortedRules.length}
              isReordering={reorderMutation.isPending}
              onMoveUp={handleMoveUp}
              onMoveDown={handleMoveDown}
              onToggleActive={handleToggleActive}
              onEdit={openEditDialog}
              onTest={openTestDialog}
              onDelete={openDeleteDialog}
            />
          ))}
        </div>
      )}

      {/* Dialogs */}
      <RuleEditDialog
        open={editDialogOpen}
        onOpenChange={setEditDialogOpen}
        editingRuleId={editingRuleId}
        ruleForm={ruleForm}
        conditions={conditions}
        onConditionsChange={setConditions}
        actions={actions}
        onActionsChange={setActions}
        isSaving={isSaving}
        onSubmit={handleSaveRule}
      />

      <DeleteConfirmDialog
        open={deleteDialogOpen}
        onOpenChange={setDeleteDialogOpen}
        title="Delete rule?"
        description="This will permanently delete this rule. This action cannot be undone."
        onConfirm={handleDelete}
        isPending={deleteMutation.isPending}
      />

      <TestRuleDialog
        open={testDialogOpen}
        onOpenChange={setTestDialogOpen}
        testInput={testInput}
        onTestInputChange={setTestInput}
        testResult={testResult}
        isPending={testMutation.isPending}
        onRunTest={handleTest}
      />

      <NlRuleDialog
        open={nlDialogOpen}
        onOpenChange={setNlDialogOpen}
        description={nlDescription}
        onDescriptionChange={setNlDescription}
        result={nlResult}
        isPending={nlMutation.isPending}
        onGenerate={handleNlGenerate}
        onConfirm={handleNlConfirm}
      />
    </div>
  );
}

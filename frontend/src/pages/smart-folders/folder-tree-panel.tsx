import { useState, useCallback, useMemo, useRef } from "react";
import {
  FolderTree,
  FolderOpen,
  ChevronRight,
  ChevronDown,
  Trash2,
  GripVertical,
  Ban,
  Check,
  Inbox,
  AlertTriangle,
  RefreshCw,
} from "lucide-react";
import {
  DndContext,
  closestCenter,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  verticalListSortingStrategy,
  useSortable,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";

import { useListFoldersApiMailAccountsAccountIdFoldersGet } from "@/services/api/mail-accounts/mail-accounts";

import { useToast } from "@/components/ui/toast";
import { DeleteConfirmDialog } from "@/components/delete-confirm-dialog";
import { AppButton } from "@/components/app-button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { MatchListItem } from "@/components/match-list-item";
import { cn, unwrapResponse } from "@/lib/utils";
import type { FolderInfo, ImapFolderListResponse } from "@/types/api";

import { type FolderNode, buildFolderTree } from "./folder-tree-utils";
import {
  useDeleteImapFolder,
  useRenameImapFolder,
  useResetSmartFolder,
  useReprocessSmartFolder,
  useUpdateExcludedFolders,
} from "./use-folder-mutations";

// ---------------------------------------------------------------------------
// Sortable Folder Row
// ---------------------------------------------------------------------------

function SortableFolderRow({
  node,
  depth,
  separator,
  onDelete,
  onReprocess,
  onToggleExclude,
  isDeleting,
  isMutating,
  expandedPaths,
  toggleExpanded,
}: {
  node: FolderNode;
  depth: number;
  separator: string;
  onDelete: (path: string) => void;
  onReprocess: (path: string) => void;
  onToggleExclude: (path: string, exclude: boolean) => void;
  isDeleting: boolean;
  isMutating: boolean;
  expandedPaths: Set<string>;
  toggleExpanded: (path: string) => void;
}) {
  const hasChildren = node.children.length > 0;
  const isExpanded = expandedPaths.has(node.fullPath);
  const isDraggable = !node.isSystemFolder;

  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({
    id: node.fullPath,
    disabled: !isDraggable,
  });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  };

  const mailCountBadge = (() => {
    const showAggregate = hasChildren && !isExpanded;
    const displayMessages = showAggregate ? node.totalMessages : node.messages;
    const displayUnseen = showAggregate ? node.totalUnseen : node.unseen;
    if (displayMessages <= 0) return null;
    return (
      <Tooltip>
        <TooltipTrigger asChild>
          <Badge variant="secondary" className="min-w-[3rem] justify-end text-xs px-2 py-0.5 h-6 shrink-0 tabular-nums">
            {displayMessages}
            {displayUnseen > 0 && (
              <span className="ml-0.5 text-blue-500 font-semibold">
                ({displayUnseen})
              </span>
            )}
          </Badge>
        </TooltipTrigger>
        <TooltipContent>
          {showAggregate
            ? `${displayMessages} messages, ${displayUnseen} of which unread (across all subfolders)`
            : `${displayMessages} messages, ${displayUnseen} of which unread`}
        </TooltipContent>
      </Tooltip>
    );
  })();

  return (
    <>
      <MatchListItem
        as="div"
        ref={setNodeRef as React.Ref<HTMLElement>}
        style={style}
        className={cn("group", node.isExcluded && "opacity-50")}
        title={node.name}
        avatar={
          <>
            {/* Indent */}
            <div style={{ width: `${depth * 20}px` }} className="shrink-0" />

            {/* Drag handle */}
            {isDraggable ? (
              <button
                type="button"
                aria-label={`Drag to reorder ${node.name}`}
                className="shrink-0 cursor-grab text-muted-foreground max-md:opacity-100 md:opacity-0 group-hover:opacity-100 focus:opacity-100 transition-opacity"
                {...attributes}
                {...listeners}
              >
                <GripVertical className="h-3.5 w-3.5" />
              </button>
            ) : (
              <span className="w-3.5 shrink-0" />
            )}

            {/* Expand/Collapse */}
            {hasChildren ? (
              <button
                type="button"
                onClick={() => toggleExpanded(node.fullPath)}
                className="shrink-0 text-muted-foreground hover:text-foreground"
              >
                {isExpanded ? (
                  <ChevronDown className="h-3.5 w-3.5" />
                ) : (
                  <ChevronRight className="h-3.5 w-3.5" />
                )}
              </button>
            ) : (
              <span className="w-3.5 shrink-0" />
            )}

            {/* Folder icon */}
            {node.isSystemFolder ? (
              <Inbox className="h-3.5 w-3.5 shrink-0 text-blue-500" />
            ) : (
              <FolderOpen className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
            )}
          </>
        }
        badges={
          <>
            {node.isExcluded && (
              <Badge variant="destructive">Excluded</Badge>
            )}

            {/* Hover actions */}
            <div className="flex items-center gap-0.5 max-md:opacity-100 md:opacity-0 group-hover:opacity-100 focus-within:opacity-100 transition-opacity shrink-0">
              {!node.isSystemFolder && (
                <AppButton
                  icon={node.isExcluded ? <Check /> : <Ban />}
                  label={node.isExcluded ? "Include in AI processing" : "Exclude from AI processing"}
                  variant="ghost"
                  color={node.isExcluded ? "success" : "default"}
                  disabled={isMutating}
                  onClick={() => onToggleExclude(node.fullPath, !node.isExcluded)}
                />
              )}
              {!node.isSystemFolder && (
                <AppButton
                  icon={<RefreshCw />}
                  label="Reevaluate emails"
                  variant="ghost"
                  disabled={isMutating}
                  onClick={() => onReprocess(node.fullPath)}
                />
              )}
              {!node.isSystemFolder && (
                <AppButton
                  icon={<Trash2 />}
                  label="Delete folder"
                  variant="ghost"
                  color="destructive"
                  onClick={() => onDelete(node.fullPath)}
                  disabled={isDeleting || isMutating}
                />
              )}
            </div>

            {mailCountBadge}
          </>
        }
      />

      {/* Children */}
      {hasChildren && isExpanded && (
        <div>
          {node.children.map((child) => (
            <SortableFolderRow
              key={child.fullPath}
              node={child}
              depth={depth + 1}
              separator={separator}
              onDelete={onDelete}
              onReprocess={onReprocess}
              onToggleExclude={onToggleExclude}
              isDeleting={isDeleting}
              isMutating={isMutating}
              expandedPaths={expandedPaths}
              toggleExpanded={toggleExpanded}
            />
          ))}
        </div>
      )}
    </>
  );
}

// ---------------------------------------------------------------------------
// Folder Tree Panel (shown in right content area)
// ---------------------------------------------------------------------------

export function FolderTreePanel({
  accountId,
  smartFolderNames,
}: {
  accountId: string;
  smartFolderNames: Set<string>;
}) {
  const [expandedPaths, setExpandedPaths] = useState<Set<string>>(new Set());
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);
  const [reprocessTarget, setReprocessTarget] = useState<string | null>(null);
  const { toast } = useToast();

  const foldersQuery = useListFoldersApiMailAccountsAccountIdFoldersGet(
    accountId,
    { counts: true },
    { query: { staleTime: 30_000 } },
  );
  const folderData = unwrapResponse<ImapFolderListResponse>(foldersQuery.data);
  const deleteMutation = useDeleteImapFolder(accountId);
  const resetMutation = useResetSmartFolder();
  const reprocessMutation = useReprocessSmartFolder();
  const renameMutation = useRenameImapFolder(accountId);
  const excludeMutation = useUpdateExcludedFolders(accountId);

  const separator = folderData?.separator ?? "/";
  const excludedFolders = folderData?.excluded_folders ?? [];
  const excludedRef = useRef(excludedFolders);
  excludedRef.current = excludedFolders;

  const folders: FolderInfo[] = useMemo(() => {
    if (!folderData?.folders) return [];
    if (typeof folderData.folders[0] === "string") {
      return (folderData.folders as unknown as string[]).map((name) => ({
        name,
      }));
    }
    return folderData.folders as FolderInfo[];
  }, [folderData]);

  const tree = useMemo(
    () => buildFolderTree(folders, separator, excludedFolders),
    [folders, separator, excludedFolders],
  );

  const allFolderIds = useMemo(() => {
    function collectIds(nodes: FolderNode[]): string[] {
      return nodes.flatMap((n) => [n.fullPath, ...collectIds(n.children)]);
    }
    // Exclude __system__ virtual node — it's not a real IMAP folder
    return collectIds(tree).filter((id) => id !== "__system__");
  }, [tree]);

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 8 } }),
  );

  const toggleExpanded = useCallback((path: string) => {
    setExpandedPaths((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  }, []);

  const handleDragEnd = useCallback(
    async (event: DragEndEvent) => {
      const { active, over } = event;
      if (!over || active.id === over.id) return;

      const oldPath = active.id as string;
      const overPath = over.id as string;

      // Prevent dropping onto the virtual __system__ group node
      if (overPath === "__system__") return;

      // Prevent dropping onto system folders (Inbox, Sent, Trash, etc.)
      const overNode = allFolderIds.includes(overPath)
        ? (() => {
            function findNode(nodes: FolderNode[], path: string): FolderNode | undefined {
              for (const n of nodes) {
                if (n.fullPath === path) return n;
                const found = findNode(n.children, path);
                if (found) return found;
              }
              return undefined;
            }
            return findNode(tree, overPath);
          })()
        : undefined;
      if (overNode?.isSystemFolder) return;

      // Prevent dropping a folder into itself or its own descendant
      if (overPath.startsWith(oldPath + separator)) return;

      // Reparent: move dragged folder into the target folder
      const oldParts = oldPath.split(separator);
      const folderName = oldParts[oldParts.length - 1] ?? "";
      const newPath = `${overPath}${separator}${folderName}`;

      // No-op if already a direct child of the target
      if (newPath === oldPath) return;

      try {
        await renameMutation.mutateAsync({ oldName: oldPath, newName: newPath });
        toast({
          title: `Moved "${folderName}"`,
          description: `Folder relocated to "${overPath}".`,
        });
      } catch {
        toast({ title: "Failed to move folder", description: "Could not rename the IMAP folder.", variant: "destructive" });
      }
    },
    [renameMutation, separator, toast, allFolderIds, tree],
  );

  const handleDelete = useCallback(
    async (path: string) => {
      const isSmart = smartFolderNames.has(path);
      setDeleteTarget(null);
      try {
        if (isSmart) {
          await resetMutation.mutateAsync(path);
          toast({ title: `Smart folder "${path}" reset — emails moved back to Inbox`, description: "All emails have been moved back to the Inbox for reprocessing." });
        } else {
          await deleteMutation.mutateAsync(path);
          toast({ title: `Folder "${path}" deleted`, description: "The folder and its contents have been removed." });
        }
      } catch {
        toast({
          title: isSmart ? "Failed to reset smart folder" : "Failed to delete folder",
          description: "An error occurred. Please try again.",
          variant: "destructive",
        });
      }
    },
    [deleteMutation, resetMutation, smartFolderNames, toast],
  );

  const handleReprocess = useCallback(
    async (path: string) => {
      try {
        await reprocessMutation.mutateAsync(path);
        setReprocessTarget(null);
        toast({ title: `Emails in "${path}" queued for reevaluation`, description: "The AI will reprocess all emails in this folder." });
      } catch {
        toast({ title: "Failed to reevaluate folder", description: "An error occurred while queuing emails for reprocessing.", variant: "destructive" });
      }
    },
    [reprocessMutation, toast],
  );

  const handleToggleExclude = useCallback(
    async (path: string, exclude: boolean) => {
      // Read from ref to avoid stale closure on rapid toggles
      const currentExcluded = [...excludedRef.current];
      let newExcluded: string[];
      if (exclude) {
        newExcluded = [...currentExcluded, path];
      } else {
        newExcluded = currentExcluded.filter((f) => f.toLowerCase() !== path.toLowerCase());
      }
      try {
        await excludeMutation.mutateAsync(newExcluded);
        toast({
          title: exclude
            ? `"${path}" excluded from AI processing`
            : `"${path}" included in AI processing`,
          description: exclude
            ? "Emails in this folder will no longer be processed by AI."
            : "Emails in this folder will now be processed by AI.",
        });
      } catch {
        toast({ title: "Failed to update exclusion list", description: "Could not update the folder exclusion setting.", variant: "destructive" });
      }
    },
    [excludeMutation, toast],
  );

  if (foldersQuery.isLoading) {
    return (
      <div className="space-y-1.5 py-2">
        <Skeleton className="h-5 w-48" />
        <Skeleton className="h-5 w-40" />
        <Skeleton className="h-5 w-44" />
        <Skeleton className="h-5 w-36" />
        <Skeleton className="h-5 w-32" />
        <Skeleton className="h-5 w-40" />
      </div>
    );
  }

  if (foldersQuery.isError) {
    return (
      <div className="flex items-center gap-2 py-4 text-sm text-destructive">
        <AlertTriangle className="h-4 w-4" />
        Failed to load folders.
        <AppButton icon={<RefreshCw />} label="Retry" variant="ghost" onClick={() => foldersQuery.refetch()}>
          Retry
        </AppButton>
      </div>
    );
  }

  if (tree.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-8 text-center">
        <FolderTree className="mb-3 h-10 w-10 text-muted-foreground" />
        <p className="text-sm text-muted-foreground">No folders found.</p>
      </div>
    );
  }

  return (
    <>
      <DndContext
        sensors={sensors}
        collisionDetection={closestCenter}
        onDragEnd={handleDragEnd}
      >
        <SortableContext
          items={allFolderIds}
          strategy={verticalListSortingStrategy}
        >
          <div className="space-y-1 p-1">
          {tree.map((node) => (
            <SortableFolderRow
              key={node.fullPath}
              node={node}
              depth={0}
              separator={separator}
              onDelete={(path) => setDeleteTarget(path)}
              onReprocess={(path) => setReprocessTarget(path)}
              onToggleExclude={handleToggleExclude}
              isDeleting={deleteMutation.isPending}
              isMutating={excludeMutation.isPending || reprocessMutation.isPending || renameMutation.isPending}
              expandedPaths={expandedPaths}
              toggleExpanded={toggleExpanded}
            />
          ))}
          </div>
        </SortableContext>
      </DndContext>

      <DeleteConfirmDialog
        open={!!deleteTarget}
        onOpenChange={(isOpen) => { if (!isOpen) setDeleteTarget(null); }}
        title={deleteTarget && smartFolderNames.has(deleteTarget) ? "Reset Smart Folder" : "Delete Folder"}
        description={
          deleteTarget && smartFolderNames.has(deleteTarget) ? (
            <>
              Are you sure you want to reset the smart folder{" "}
              <span className="font-medium">{deleteTarget}</span>?
              <br /><br />
              This will:
              <ul className="mt-1 list-disc pl-4 text-left text-xs">
                <li>Move all emails back to Inbox</li>
                <li>Delete the IMAP folder</li>
                <li>Remove all assignment records</li>
                <li>Re-process the emails on the next poll cycle</li>
              </ul>
            </>
          ) : (
            <>
              Are you sure you want to delete the folder{" "}
              <span className="font-medium">{deleteTarget}</span>?
              Emails will be moved back to Inbox before the folder is removed.
            </>
          )
        }
        onConfirm={() => {
          if (deleteTarget) handleDelete(deleteTarget);
        }}
        isPending={deleteMutation.isPending || resetMutation.isPending}
      />

      <DeleteConfirmDialog
        open={!!reprocessTarget}
        onOpenChange={(isOpen) => { if (!isOpen) setReprocessTarget(null); }}
        title="Reevaluate Emails"
        description={
          <>
            Re-queue all emails in{" "}
            <span className="font-medium">{reprocessTarget}</span> for AI reevaluation?
            <br /><br />
            This will:
            <ul className="mt-1 list-disc pl-4 text-left text-xs">
              <li>Re-analyse all emails through the AI pipeline</li>
              <li>Keep the folder and emails in place</li>
            </ul>
          </>
        }
        onConfirm={() => {
          if (reprocessTarget) handleReprocess(reprocessTarget);
        }}
        isPending={reprocessMutation.isPending}
        confirmLabel="Reevaluate"
        confirmVariant="default"
      />
    </>
  );
}

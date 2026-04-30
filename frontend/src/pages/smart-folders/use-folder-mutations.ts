import { useQueryClient, useMutation } from "@tanstack/react-query";

import {
  getGetFolderSummaryApiFoldersSummaryGetQueryKey,
  getListAssignedFoldersApiFoldersGetQueryKey,
  resetSmartFolderApiFoldersByNameFolderNameDelete,
  reprocessSmartFolderApiFoldersByNameFolderNameReprocessPost,
} from "@/services/api/folders/folders";
import {
  getListFoldersApiMailAccountsAccountIdFoldersGetQueryKey,
  deleteImapFolderApiMailAccountsAccountIdFoldersFolderPathDelete,
  renameImapFolderApiMailAccountsAccountIdFoldersRenamePost,
  updateExcludedFoldersApiMailAccountsAccountIdExcludedFoldersPut,
} from "@/services/api/mail-accounts/mail-accounts";

import type {
  FolderSummaryListResponse,
  FolderInfo,
  ImapFolderListResponse,
} from "@/types/api";

export function useDeleteImapFolder(accountId: string) {
  const queryClient = useQueryClient();
  const queryKey = getListFoldersApiMailAccountsAccountIdFoldersGetQueryKey(accountId, { counts: true });
  return useMutation({
    mutationFn: (folderPath: string) =>
      deleteImapFolderApiMailAccountsAccountIdFoldersFolderPathDelete(
        accountId,
        encodeURIComponent(folderPath),
        { move_to_inbox: true },
      ),
    onMutate: async (folderPath: string) => {
      await queryClient.cancelQueries({ queryKey });
      const previous = queryClient.getQueryData<{ data: ImapFolderListResponse }>(queryKey);
      if (previous?.data) {
        const sep = previous.data.separator;
        queryClient.setQueryData(queryKey, {
          ...previous,
          data: {
            ...previous.data,
            folders: (previous.data.folders as FolderInfo[]).filter(
              (f) => f.name !== folderPath && !f.name.startsWith(folderPath + sep),
            ),
          },
        });
      }
      return { previous };
    },
    onError: (_err, _vars, context) => {
      if (context?.previous) {
        queryClient.setQueryData(queryKey, context.previous);
      }
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey });
    },
  });
}

export function useRenameImapFolder(accountId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ oldName, newName }: { oldName: string; newName: string }) =>
      renameImapFolderApiMailAccountsAccountIdFoldersRenamePost(
        accountId,
        { old_name: oldName, new_name: newName },
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: getListFoldersApiMailAccountsAccountIdFoldersGetQueryKey(accountId, { counts: true }),
      });
    },
  });
}

export function useResetSmartFolder() {
  const queryClient = useQueryClient();
  const summaryKey = getGetFolderSummaryApiFoldersSummaryGetQueryKey();
  const listKeyPrefix = getListAssignedFoldersApiFoldersGetQueryKey();
  return useMutation({
    mutationFn: (folderName: string) =>
      resetSmartFolderApiFoldersByNameFolderNameDelete(encodeURIComponent(folderName)),
    onMutate: async (folderName: string) => {
      await queryClient.cancelQueries({ queryKey: summaryKey });
      await queryClient.cancelQueries({ queryKey: listKeyPrefix });
      await queryClient.cancelQueries({ predicate: (q) => (q.queryKey[0] as string)?.includes("/folders") });

      // Optimistically remove from summary cache
      const prevSummary = queryClient.getQueryData(summaryKey);
      queryClient.setQueriesData<{ data: FolderSummaryListResponse; status: number; headers: Headers }>(
        { queryKey: summaryKey },
        (old) => {
          if (!old?.data) return old;
          const filtered = old.data.items.filter((s) => s.folder !== folderName);
          return { ...old, data: { ...old.data, items: filtered, total: filtered.length } };
        },
      );

      return { prevSummary };
    },
    onError: (_err, _vars, context) => {
      if (context?.prevSummary) {
        queryClient.setQueryData(summaryKey, context.prevSummary);
      }
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: summaryKey });
      queryClient.invalidateQueries({ queryKey: listKeyPrefix });
      queryClient.invalidateQueries({ predicate: (q) => (q.queryKey[0] as string)?.includes("/folders") });
    },
  });
}

export function useReprocessSmartFolder() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (folderName: string) =>
      reprocessSmartFolderApiFoldersByNameFolderNameReprocessPost(encodeURIComponent(folderName)),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: getGetFolderSummaryApiFoldersSummaryGetQueryKey() });
      queryClient.invalidateQueries({ queryKey: getListAssignedFoldersApiFoldersGetQueryKey() });
    },
  });
}

export function useUpdateExcludedFolders(accountId: string) {
  const queryClient = useQueryClient();
  const queryKey = getListFoldersApiMailAccountsAccountIdFoldersGetQueryKey(accountId, { counts: true });
  return useMutation({
    mutationFn: (excludedFolders: string[]) =>
      updateExcludedFoldersApiMailAccountsAccountIdExcludedFoldersPut(
        accountId,
        { excluded_folders: excludedFolders },
      ),
    onMutate: async (newExcluded: string[]) => {
      await queryClient.cancelQueries({ queryKey });
      const previous = queryClient.getQueryData<{ data: ImapFolderListResponse }>(queryKey);
      if (previous?.data) {
        queryClient.setQueryData(queryKey, {
          ...previous,
          data: { ...previous.data, excluded_folders: newExcluded },
        });
      }
      return { previous };
    },
    onError: (_err, _vars, context) => {
      if (context?.previous) {
        queryClient.setQueryData(queryKey, context.previous);
      }
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey });
    },
  });
}

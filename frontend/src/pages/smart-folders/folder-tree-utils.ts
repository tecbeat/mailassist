import type { FolderInfo } from "@/types/api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type FolderNode = {
  name: string;
  fullPath: string;
  messages: number;
  unseen: number;
  /** Sum of messages across this node + all descendants */
  totalMessages: number;
  /** Sum of unseen across this node + all descendants */
  totalUnseen: number;
  children: FolderNode[];
  isSystemFolder: boolean;
  isExcluded: boolean;
};

export const SYSTEM_FOLDERS = new Set([
  "inbox", "spam", "junk", "trash", "drafts", "sent",
  "sent messages", "deleted messages", "junk e-mail",
  "deleted items", "sent items", "archive", "archives",
]);

/** Logical display order for system folders (lower = higher in tree). */
export const SYSTEM_FOLDER_ORDER: Record<string, number> = {
  inbox: 0,
  sent: 1,
  "sent messages": 1,
  "sent items": 1,
  drafts: 2,
  archive: 3,
  archives: 3,
  trash: 4,
  "deleted messages": 4,
  "deleted items": 4,
  spam: 5,
  junk: 5,
  "junk e-mail": 5,
};

export function isSystemFolder(name: string): boolean {
  return SYSTEM_FOLDERS.has(name.toLowerCase());
}

// ---------------------------------------------------------------------------
// Build tree from flat folder list
// ---------------------------------------------------------------------------

export function buildFolderTree(
  folders: FolderInfo[],
  separator: string,
  excludedFolders: string[],
): FolderNode[] {
  const excludedSet = new Set(excludedFolders.map((f) => f.toLowerCase()));
  const root: FolderNode = {
    name: "",
    fullPath: "",
    messages: 0,
    unseen: 0,
    totalMessages: 0,
    totalUnseen: 0,
    children: [],
    isSystemFolder: false,
    isExcluded: false,
  };

  const nodeMap = new Map<string, FolderNode>();

  for (const folder of folders) {
    const parts = folder.name.split(separator);
    let currentPath = "";
    let parent = root;

    for (let i = 0; i < parts.length; i++) {
      const part = parts[i]!;
      currentPath = currentPath ? `${currentPath}${separator}${part}` : part;

      let node = nodeMap.get(currentPath);
      if (!node) {
        node = {
          name: part,
          fullPath: currentPath,
          messages: 0,
          unseen: 0,
          totalMessages: 0,
          totalUnseen: 0,
          children: [],
          isSystemFolder: isSystemFolder(currentPath),
          isExcluded: excludedSet.has(currentPath.toLowerCase()),
        };
        nodeMap.set(currentPath, node);
        parent.children.push(node);
      }

      // Apply counts only to the leaf (full path matches folder name)
      if (i === parts.length - 1) {
        node.messages = folder.messages ?? 0;
        node.unseen = folder.unseen ?? 0;
      }

      parent = node;
    }
  }

  // Post-process: compute aggregate totals and sort
  function computeTotals(node: FolderNode): void {
    node.totalMessages = node.messages;
    node.totalUnseen = node.unseen;
    for (const child of node.children) {
      computeTotals(child);
      node.totalMessages += child.totalMessages;
      node.totalUnseen += child.totalUnseen;
    }
  }

  function sortChildren(nodes: FolderNode[]): FolderNode[] {
    return nodes
      .map((n) => ({ ...n, children: sortChildren(n.children) }))
      .sort((a, b) => {
        const aSystem = a.isSystemFolder;
        const bSystem = b.isSystemFolder;
        if (aSystem && !bSystem) return -1;
        if (!aSystem && bSystem) return 1;
        if (aSystem && bSystem) {
          const aOrder = SYSTEM_FOLDER_ORDER[a.fullPath.toLowerCase()] ?? 99;
          const bOrder = SYSTEM_FOLDER_ORDER[b.fullPath.toLowerCase()] ?? 99;
          return aOrder - bOrder;
        }
        return a.name.localeCompare(b.name);
      });
  }

  for (const child of root.children) {
    computeTotals(child);
  }
  const sorted = sortChildren(root.children);

  // Group all top-level system folders under a virtual "Inbox" parent so the
  // user can collapse them to reduce visual noise.
  const systemNodes = sorted.filter((n) => n.isSystemFolder);
  const userNodes = sorted.filter((n) => !n.isSystemFolder);

  if (systemNodes.length > 0) {
    const inboxGroup: FolderNode = {
      name: "Inbox",
      fullPath: "__system__",
      messages: 0,
      unseen: 0,
      totalMessages: systemNodes.reduce((s, n) => s + n.totalMessages, 0),
      totalUnseen: systemNodes.reduce((s, n) => s + n.totalUnseen, 0),
      children: systemNodes,
      isSystemFolder: true,
      isExcluded: false,
    };
    return [inboxGroup, ...userNodes];
  }
  return userNodes;
}

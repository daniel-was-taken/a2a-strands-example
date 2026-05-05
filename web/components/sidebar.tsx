"use client";

import * as React from "react";
import { Plus, Search, Trash2, AlertTriangle, MoreHorizontal, FileText } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { cn, formatRelative } from "@/lib/utils";
import type { ConversationSummary } from "@/lib/types";

interface Props {
  conversations: ConversationSummary[];
  loaded: boolean;
  selectedId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
}

export function Sidebar({ conversations, loaded, selectedId, onSelect, onNew, onDelete }: Props) {
  const [query, setQuery] = React.useState("");
  const [pendingDelete, setPendingDelete] = React.useState<string | null>(null);

  const filtered = React.useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return conversations;
    return conversations.filter((c) => c.title.toLowerCase().includes(q));
  }, [conversations, query]);

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-2 border-b border-border px-4 py-3">
        <div className="grid h-8 w-8 place-items-center rounded-md bg-primary text-primary-foreground">
          <FileText className="h-4 w-4" />
        </div>
        <div className="text-sm font-semibold">BRD Specialist</div>
      </div>

      <div className="space-y-2 p-3">
        <Button onClick={onNew} className="w-full" size="sm">
          <Plus className="h-4 w-4" />
          New BRD
        </Button>
        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            type="search"
            placeholder="Search…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="pl-8"
          />
        </div>
      </div>

      <ScrollArea className="flex-1 px-2 scrollbar-subtle">
        {!loaded && <SidebarSkeleton />}
        {loaded && !filtered.length && (
          <div className="px-3 py-10 text-center">
            <div className="text-sm font-medium">
              {conversations.length ? "No matches" : "No conversations yet"}
            </div>
            <div className="mt-1 text-xs text-muted-foreground">
              {conversations.length
                ? "Try a different search term"
                : "Start a new BRD to begin"}
            </div>
          </div>
        )}
        <ul className="space-y-0.5 pb-3">
          {filtered.map((c) => {
            const active = c.id === selectedId;
            const needsAttention = c.status !== "active";
            return (
              <li key={c.id}>
                <div
                  role="button"
                  tabIndex={0}
                  onClick={() => onSelect(c.id)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      onSelect(c.id);
                    }
                  }}
                  className={cn(
                    "group flex cursor-pointer items-center gap-2 rounded-md px-2 py-2 transition-colors",
                    active ? "bg-accent text-accent-foreground" : "hover:bg-accent/60",
                  )}
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-1.5">
                      <span className="truncate text-sm font-medium">{c.title}</span>
                      {needsAttention && (
                        <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-amber-500" />
                      )}
                    </div>
                    <div className="truncate text-xs text-muted-foreground">
                      {formatRelative(c.updated_at)}
                    </div>
                  </div>
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild onClick={(e) => e.stopPropagation()}>
                      <Button
                        variant="ghost"
                        size="icon"
                        className={cn(
                          "h-7 w-7 shrink-0 opacity-0 group-hover:opacity-100",
                          active && "opacity-100",
                        )}
                        aria-label="Conversation actions"
                      >
                        <MoreHorizontal className="h-4 w-4" />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                      <DropdownMenuItem
                        onSelect={(e) => {
                          e.preventDefault();
                          setPendingDelete(c.id);
                        }}
                        className="text-destructive focus:text-destructive"
                      >
                        <Trash2 className="h-4 w-4" />
                        Delete
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                </div>
              </li>
            );
          })}
        </ul>
      </ScrollArea>

      <Dialog open={pendingDelete !== null} onOpenChange={(o) => !o && setPendingDelete(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete conversation?</DialogTitle>
            <DialogDescription>
              This permanently removes the conversation thread, BRD, and activity history.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="gap-2">
            <Button variant="outline" onClick={() => setPendingDelete(null)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={() => {
                if (pendingDelete) onDelete(pendingDelete);
                setPendingDelete(null);
              }}
            >
              Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function SidebarSkeleton() {
  return (
    <div className="space-y-2 px-1 py-2">
      {[0, 1, 2, 3].map((i) => (
        <div key={i} className="h-12 rounded-md shimmer" />
      ))}
    </div>
  );
}

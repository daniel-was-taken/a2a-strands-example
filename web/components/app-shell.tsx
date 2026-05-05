"use client";

import * as React from "react";
import { toast } from "sonner";
import { Menu, FileText, PanelRightOpen, PanelRightClose } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Sidebar } from "@/components/sidebar";
import { ChatPane } from "@/components/chat-pane";
import { RightPanel } from "@/components/right-panel";
import { api } from "@/lib/api";
import type { Conversation, ConversationSummary } from "@/lib/types";
import { cn } from "@/lib/utils";

const SIDEBAR_POLL_MS = 15_000;

export default function AppShell() {
  const [conversations, setConversations] = React.useState<ConversationSummary[]>([]);
  const [conversationsLoaded, setConversationsLoaded] = React.useState(false);
  const [selectedId, setSelectedId] = React.useState<string | null>(null);
  const [current, setCurrent] = React.useState<Conversation | null>(null);
  const [sidebarOpenMobile, setSidebarOpenMobile] = React.useState(false);
  const [previewOpen, setPreviewOpen] = React.useState(true);

  const refreshConversations = React.useCallback(async () => {
    try {
      const list = await api.listConversations();
      // Most recent first.
      list.sort((a, b) => b.updated_at.localeCompare(a.updated_at));
      setConversations(list);
      setConversationsLoaded(true);
    } catch (err) {
      setConversationsLoaded(true);
      console.error("Failed to list conversations:", err);
    }
  }, []);

  const refreshCurrent = React.useCallback(async (id: string) => {
    try {
      const conv = await api.getConversation(id);
      setCurrent(conv);
    } catch (err) {
      console.error("Failed to load conversation:", err);
    }
  }, []);

  // Initial load
  React.useEffect(() => {
    refreshConversations();
  }, [refreshConversations]);

  // Background polling so new conversations created in other tabs show up.
  React.useEffect(() => {
    if (!selectedId) return;
    const id = setInterval(refreshConversations, SIDEBAR_POLL_MS);
    return () => clearInterval(id);
  }, [selectedId, refreshConversations]);

  const handleSelect = React.useCallback(
    async (id: string) => {
      setSelectedId(id);
      setSidebarOpenMobile(false);
      await refreshCurrent(id);
    },
    [refreshCurrent],
  );

  const handleNew = React.useCallback(async () => {
    try {
      const conv = await api.createConversation();
      setCurrent(conv);
      setSelectedId(conv.id);
      setSidebarOpenMobile(false);
      await refreshConversations();
    } catch (err) {
      toast.error((err as Error).message);
    }
  }, [refreshConversations]);

  const handleDelete = React.useCallback(
    async (id: string) => {
      try {
        await api.deleteConversation(id);
        if (selectedId === id) {
          setSelectedId(null);
          setCurrent(null);
        }
        await refreshConversations();
        toast.success("Conversation deleted");
      } catch (err) {
        toast.error((err as Error).message);
      }
    },
    [selectedId, refreshConversations],
  );

  // Derived: latest BRD message in the current conversation (if any).
  const latestBrd = React.useMemo(() => {
    if (!current?.messages?.length) return null;
    for (let i = current.messages.length - 1; i >= 0; i--) {
      const m = current.messages[i];
      if (m.role === "agent" && /problem statement/i.test(m.content) && /functional requirements/i.test(m.content)) {
        return m;
      }
    }
    return null;
  }, [current?.messages]);

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-background">
      {/* Sidebar */}
      <aside
        className={cn(
          "z-40 w-72 shrink-0 border-r border-border bg-card transition-transform md:relative md:translate-x-0",
          "fixed inset-y-0 left-0",
          sidebarOpenMobile ? "translate-x-0" : "-translate-x-full md:translate-x-0",
        )}
      >
        <Sidebar
          conversations={conversations}
          loaded={conversationsLoaded}
          selectedId={selectedId}
          onSelect={handleSelect}
          onNew={handleNew}
          onDelete={handleDelete}
        />
      </aside>
      {/* Mobile backdrop */}
      {sidebarOpenMobile && (
        <div
          className="fixed inset-0 z-30 bg-black/40 md:hidden"
          onClick={() => setSidebarOpenMobile(false)}
        />
      )}

      {/* Main */}
      <main className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 items-center gap-2 border-b border-border bg-background px-4">
          <Button
            variant="ghost"
            size="icon"
            className="md:hidden"
            onClick={() => setSidebarOpenMobile((o) => !o)}
            aria-label="Toggle sidebar"
          >
            <Menu className="h-5 w-5" />
          </Button>
          <div className="flex items-center gap-2">
            <div className="grid h-8 w-8 place-items-center rounded-md bg-primary text-primary-foreground">
              <FileText className="h-4 w-4" />
            </div>
            <div className="min-w-0">
              <div className="truncate text-sm font-semibold">
                {current?.title ?? "BRD Specialist"}
              </div>
              <div className="text-xs text-muted-foreground">
                {current
                  ? `${current.messages.length} message${current.messages.length === 1 ? "" : "s"}`
                  : "Evidence-grounded BRD generation"}
              </div>
            </div>
          </div>
          <div className="ml-auto flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setPreviewOpen((o) => !o)}
              className="hidden lg:inline-flex"
            >
              {previewOpen ? (
                <>
                  <PanelRightClose className="h-4 w-4" />
                  Hide panel
                </>
              ) : (
                <>
                  <PanelRightOpen className="h-4 w-4" />
                  Show panel
                </>
              )}
            </Button>
          </div>
        </header>

        <div className="flex min-h-0 flex-1">
          <div className="flex min-w-0 flex-1 flex-col">
            <ChatPane
              conversation={current}
              onConversationChange={setCurrent}
              onNew={handleNew}
              onAfterMutation={refreshConversations}
              selectedId={selectedId}
            />
          </div>

          {/* Right panel: tabbed view with BRD preview, workflow, and logs */}
          <aside
            className={cn(
              "hidden w-[420px] shrink-0 flex-col border-l border-border bg-card lg:flex xl:w-[480px]",
              !previewOpen && "lg:hidden",
            )}
          >
            <RightPanel conversation={current} latestBrd={latestBrd} />
          </aside>
        </div>
      </main>
    </div>
  );
}

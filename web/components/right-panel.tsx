"use client";

import * as React from "react";
import { FileText, Activity, Terminal } from "lucide-react";
import { BrdPreview } from "@/components/brd-preview";
import { WorkflowTimeline, LogStream } from "@/components/activity-timeline";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import type { Conversation, Message } from "@/lib/types";

type TabValue = "brd" | "workflow" | "logs";

interface Props {
  conversation: Conversation | null;
  latestBrd: Message | null;
}

/**
 * Unified right-hand panel with three coexisting views:
 *   - BRD preview  (only enabled when a BRD exists)
 *   - Workflow activity timeline
 *   - Server log stream
 *
 * All three are mounted at once so switching tabs is instant and the log
 * stream keeps its SSE connection alive regardless of which tab is visible.
 */
export function RightPanel({ conversation, latestBrd }: Props) {
  const [tab, setTab] = React.useState<TabValue>(latestBrd ? "brd" : "workflow");
  const prevHasBrd = React.useRef<boolean>(!!latestBrd);

  // When a BRD first appears, auto-switch to it — but respect the user's
  // manual choice afterwards.
  React.useEffect(() => {
    const hasBrd = !!latestBrd;
    if (hasBrd && !prevHasBrd.current) setTab("brd");
    if (!hasBrd && prevHasBrd.current && tab === "brd") setTab("workflow");
    prevHasBrd.current = hasBrd;
  }, [latestBrd, tab]);

  const eventCount = conversation?.events?.length ?? 0;

  return (
    <Tabs
      value={tab}
      onValueChange={(v) => setTab(v as TabValue)}
      className="flex h-full min-h-0 flex-col"
    >
      <div className="border-b border-border px-3 py-2">
        <TabsList className="grid w-full grid-cols-3">
          <TabsTrigger value="brd" disabled={!latestBrd} className="gap-1.5">
            <FileText className="h-3.5 w-3.5" />
            BRD
          </TabsTrigger>
          <TabsTrigger value="workflow" className="gap-1.5">
            <Activity className="h-3.5 w-3.5" />
            Workflow
            {eventCount > 0 && (
              <Badge variant="secondary" className="ml-1 h-4 px-1.5 text-[10px]">
                {eventCount}
              </Badge>
            )}
          </TabsTrigger>
          <TabsTrigger value="logs" className="gap-1.5">
            <Terminal className="h-3.5 w-3.5" />
            Logs
          </TabsTrigger>
        </TabsList>
      </div>

      {/*
        Keep all three views mounted so SSE subscriptions survive tab
        switches. Radix hides inactive TabsContent via data attributes; we
        additionally force the panel to fill the remaining height.
      */}
      <div className="relative min-h-0 flex-1">
        <TabsContent
          value="brd"
          forceMount
          className="absolute inset-0 m-0 data-[state=inactive]:hidden"
        >
          {latestBrd ? (
            <BrdPreview content={latestBrd.content} timestamp={latestBrd.timestamp} />
          ) : (
            <EmptyState
              icon={<FileText className="h-6 w-6" />}
              title="No BRD yet"
              description="Once the orchestrator drafts a BRD it will appear here."
            />
          )}
        </TabsContent>
        <TabsContent
          value="workflow"
          forceMount
          className="absolute inset-0 m-0 data-[state=inactive]:hidden"
        >
          <WorkflowTimeline conversation={conversation} />
        </TabsContent>
        <TabsContent
          value="logs"
          forceMount
          className="absolute inset-0 m-0 data-[state=inactive]:hidden"
        >
          <LogStream />
        </TabsContent>
      </div>
    </Tabs>
  );
}

function EmptyState({
  icon,
  title,
  description,
}: {
  icon: React.ReactNode;
  title: string;
  description: string;
}) {
  return (
    <div className="grid h-full place-items-center px-6 text-center">
      <div>
        <div className="mx-auto mb-3 grid h-10 w-10 place-items-center rounded-full bg-muted text-muted-foreground">
          {icon}
        </div>
        <div className="text-sm font-medium">{title}</div>
        <div className="mt-1 text-xs text-muted-foreground">{description}</div>
      </div>
    </div>
  );
}

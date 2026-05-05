"use client";

import * as React from "react";
import {
  Activity,
  Bot,
  Database,
  ExternalLink,
  GitBranch,
  ShieldCheck,
  UserCheck,
  CheckCircle2,
  AlertCircle,
  Clock,
  Circle,
} from "lucide-react";
import type { Conversation, ActivityEvent, LogEvent } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { formatTime } from "@/lib/utils";

/* -- Agent metadata ------------------------------------------------------ */

const AGENT_STYLES: Record<
  string,
  { icon: React.ElementType; label: string; chipClass: string }
> = {
  orchestrator: {
    icon: Bot,
    label: "Orchestrator",
    chipClass: "bg-violet-100 text-violet-900 dark:bg-violet-900/30 dark:text-violet-200",
  },
  database_agent: {
    icon: Database,
    label: "Database Agent",
    chipClass: "bg-sky-100 text-sky-900 dark:bg-sky-900/30 dark:text-sky-200",
  },
  graph_reviewer: {
    icon: GitBranch,
    label: "Graph Reviewer",
    chipClass: "bg-emerald-100 text-emerald-900 dark:bg-emerald-900/30 dark:text-emerald-200",
  },
  research_team: {
    icon: GitBranch,
    label: "Research Team",
    chipClass: "bg-teal-100 text-teal-900 dark:bg-teal-900/30 dark:text-teal-200",
  },
  brd_specialist: {
    icon: Bot,
    label: "BRD Specialist",
    chipClass: "bg-indigo-100 text-indigo-900 dark:bg-indigo-900/30 dark:text-indigo-200",
  },
  safety_reviewer: {
    icon: ShieldCheck,
    label: "Safety Reviewer",
    chipClass: "bg-amber-100 text-amber-900 dark:bg-amber-900/30 dark:text-amber-200",
  },
  human: {
    icon: UserCheck,
    label: "Human",
    chipClass: "bg-slate-100 text-slate-900 dark:bg-slate-700/40 dark:text-slate-200",
  },
};

function resolveAgent(agent: string) {
  return (
    AGENT_STYLES[agent] ?? {
      icon: Bot,
      label: agent.replace(/_/g, " ") || "Agent",
      chipClass: "bg-muted text-foreground",
    }
  );
}

function prettyAction(action: string): string {
  return action.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function actionIcon(action: string): React.ReactNode {
  if (action.includes("completed") || action.includes("approved") || action.includes("confirmed")) {
    return <CheckCircle2 className="h-3 w-3 text-emerald-500" />;
  }
  if (action.includes("failed") || action.includes("rejected") || action.includes("reject")) {
    return <AlertCircle className="h-3 w-3 text-destructive" />;
  }
  if (action.includes("pending") || action.includes("awaiting") || action.includes("started")) {
    return <Clock className="h-3 w-3 text-amber-500" />;
  }
  return <Circle className="h-2.5 w-2.5 text-muted-foreground" />;
}

/* -- Workflow timeline --------------------------------------------------- */

export function WorkflowTimeline({ conversation }: { conversation: Conversation | null }) {
  const events = conversation?.events ?? [];
  if (!events.length) {
    return (
      <div className="grid h-full place-items-center py-16 text-center">
        <div>
          <Activity className="mx-auto mb-2 h-6 w-6 text-muted-foreground" />
          <div className="text-sm font-medium">No activity yet</div>
          <div className="text-xs text-muted-foreground">
            Send a message to see agents coordinate here.
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto px-4 py-3 scrollbar-subtle">
      <ol className="relative space-y-3 pl-5 before:absolute before:left-2 before:top-1 before:bottom-1 before:w-px before:bg-border">
        {events.map((e, i) => (
          <TimelineItem key={`${e.timestamp}-${i}`} event={e} />
        ))}
      </ol>
    </div>
  );
}

function TimelineItem({ event }: { event: ActivityEvent }) {
  const { icon: Icon, label, chipClass } = resolveAgent(event.agent);
  return (
    <li className="relative">
      <span className="absolute -left-[18px] top-1 grid h-4 w-4 place-items-center rounded-full border border-border bg-background">
        {actionIcon(event.action)}
      </span>
      <div className="flex flex-wrap items-center gap-1.5 text-xs">
        <span
          className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium ${chipClass}`}
        >
          <Icon className="h-3 w-3" />
          {label}
        </span>
        <span className="font-medium text-foreground">{prettyAction(event.action)}</span>
        {event.duration_ms != null && (
          <span className="rounded bg-muted px-1 py-0.5 text-[10px] tabular-nums text-muted-foreground">
            {event.duration_ms < 1000
              ? `${Math.round(event.duration_ms)}ms`
              : `${(event.duration_ms / 1000).toFixed(1)}s`}
          </span>
        )}
        {event.trace_url && (
          <a
            href={event.trace_url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-0.5 text-[10px] text-blue-500 hover:text-blue-600 hover:underline"
          >
            <ExternalLink className="h-2.5 w-2.5" />
            trace
          </a>
        )}
        <span className="ml-auto text-[10px] text-muted-foreground">
          {formatTime(event.timestamp)}
        </span>
      </div>
      {event.detail && <div className="mt-1 text-xs text-muted-foreground">{event.detail}</div>}
    </li>
  );
}

/* -- Server log stream --------------------------------------------------- */

const LOG_LEVEL_CLASS: Record<string, string> = {
  DEBUG: "text-muted-foreground",
  INFO: "text-foreground",
  WARNING: "text-amber-500",
  ERROR: "text-destructive",
  CRITICAL: "text-destructive font-semibold",
};

const MAX_LOG_LINES = 200;

export function LogStream() {
  const [logs, setLogs] = React.useState<LogEvent[]>([]);
  const [connected, setConnected] = React.useState(false);
  const bodyRef = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    const base = process.env.NEXT_PUBLIC_API_BASE ?? "";
    let es: EventSource | null = null;
    let backoff = 1000;
    const MAX_BACKOFF = 30_000;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    let disposed = false;

    const connect = () => {
      if (disposed) return;
      es = new EventSource(`${base}/logs/stream`);
      es.onopen = () => {
        backoff = 1000;
        setConnected(true);
      };
      es.onmessage = (e) => {
        try {
          const data = JSON.parse(e.data) as LogEvent;
          setLogs((prev) => {
            const next = prev.concat(data);
            return next.length > MAX_LOG_LINES ? next.slice(-MAX_LOG_LINES) : next;
          });
        } catch {
          /* ignore malformed frame */
        }
      };
      es.onerror = () => {
        setConnected(false);
        es?.close();
        retryTimer = setTimeout(connect, backoff);
        backoff = Math.min(backoff * 2, MAX_BACKOFF);
      };
    };

    connect();
    return () => {
      disposed = true;
      if (retryTimer) clearTimeout(retryTimer);
      es?.close();
    };
  }, []);

  React.useEffect(() => {
    const el = bodyRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [logs.length]);

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-border bg-muted/40 px-4 py-2">
        <div className="text-xs font-medium">Server logs</div>
        <Badge variant={connected ? "success" : "warning"} className="text-[10px]">
          {connected ? "connected" : "reconnecting"}
        </Badge>
      </div>
      <div
        ref={bodyRef}
        className="flex-1 overflow-y-auto bg-background/50 p-3 font-mono text-[11px] leading-snug scrollbar-subtle"
      >
        {!logs.length && <div className="text-muted-foreground">Waiting for log events…</div>}
        {logs.map((l, i) => (
          <div key={i} className={LOG_LEVEL_CLASS[l.level] ?? ""}>
            <span className="text-muted-foreground">[{l.level}]</span>{" "}
            <span className="text-muted-foreground">{l.logger}:</span> {l.message}
          </div>
        ))}
      </div>
    </div>
  );
}

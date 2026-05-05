"use client";

import * as React from "react";
import { toast } from "sonner";
import { Copy, Check, User, Bot } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { Message } from "@/lib/types";
import { cn, formatTime } from "@/lib/utils";
import { renderMarkdown, isBrdDocument } from "@/lib/markdown";

interface ChatThreadProps {
  messages: Message[];
  pendingUserMsg: string | null;
}

export function ChatThread({ messages, pendingUserMsg }: ChatThreadProps) {
  return (
    <div className="space-y-4">
      {messages.map((m, i) => (
        <Bubble key={i} message={m} />
      ))}
      {pendingUserMsg && (
        <Bubble
          message={{
            role: "user",
            content: pendingUserMsg,
            timestamp: new Date().toISOString(),
          }}
        />
      )}
    </div>
  );
}

function Bubble({ message }: { message: Message }) {
  const isUser = message.role === "user";
  const [copied, setCopied] = React.useState(false);
  const brd = !isUser && isBrdDocument(message.content);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(message.content);
      setCopied(true);
      toast.success("Copied");
      setTimeout(() => setCopied(false), 1500);
    } catch {
      toast.error("Copy failed");
    }
  };

  if (isUser) {
    return (
      <div className="flex items-start justify-end gap-3">
        <div className="max-w-[85%] rounded-2xl rounded-tr-sm bg-primary px-4 py-2.5 text-sm text-primary-foreground shadow-sm">
          <div className="whitespace-pre-wrap break-words">{message.content}</div>
          <div className="mt-1 text-right text-[10px] text-primary-foreground/60">
            {formatTime(message.timestamp)}
          </div>
        </div>
        <div className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-muted">
          <User className="h-4 w-4" />
        </div>
      </div>
    );
  }

  return (
    <div className="flex items-start gap-3">
      <div className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-primary text-primary-foreground">
        <Bot className="h-4 w-4" />
      </div>
      <div className="group min-w-0 flex-1">
        <div
          className={cn(
            "relative rounded-2xl rounded-tl-sm border border-border bg-card px-4 py-3 shadow-sm",
            brd && "border-primary/30 bg-primary/[0.02]",
          )}
        >
          {brd && (
            <div className="mb-2 inline-flex items-center gap-1.5 rounded-full bg-primary/10 px-2 py-0.5 text-[11px] font-medium text-primary">
              Business Requirements Document
            </div>
          )}
          <div
            className="md-body max-w-none"
            // eslint-disable-next-line react/no-danger
            dangerouslySetInnerHTML={{ __html: renderMarkdown(message.content) }}
          />
          <div className="mt-2 flex items-center justify-between">
            <span className="text-[10px] text-muted-foreground">
              {formatTime(message.timestamp)}
            </span>
            <Button
              variant="ghost"
              size="sm"
              onClick={copy}
              className="h-6 px-2 text-xs opacity-0 transition-opacity group-hover:opacity-100"
            >
              {copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
              {copied ? "Copied" : "Copy"}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

export function TypingBubble() {
  return (
    <div className="mt-4 flex items-start gap-3">
      <div className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-primary text-primary-foreground">
        <Bot className="h-4 w-4" />
      </div>
      <div className="rounded-2xl rounded-tl-sm border border-border bg-card px-4 py-3 shadow-sm">
        <div className="flex items-center gap-1.5">
          <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-muted-foreground [animation-delay:-0.3s]" />
          <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-muted-foreground [animation-delay:-0.15s]" />
          <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-muted-foreground" />
        </div>
      </div>
    </div>
  );
}

export function StreamingBubble({ text }: { text: string }) {
  return (
    <div className="mt-4 flex items-start gap-3">
      <div className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-primary text-primary-foreground">
        <Bot className="h-4 w-4" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="rounded-2xl rounded-tl-sm border border-border bg-card px-4 py-3 shadow-sm">
          <pre className="streaming-cursor whitespace-pre-wrap break-words font-sans text-sm">
            {text}
          </pre>
        </div>
      </div>
    </div>
  );
}

"use client";

import * as React from "react";
import { toast } from "sonner";
import { ArrowUp, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { api, sendMessageStream } from "@/lib/api";
import type { Conversation } from "@/lib/types";
import { ChatThread, TypingBubble, StreamingBubble } from "@/components/chat-thread";
import { WelcomeState } from "@/components/welcome-state";
import { ApprovalCard } from "@/components/approval-card";
import { EvidenceCard } from "@/components/evidence-card";
import { cn } from "@/lib/utils";

interface Props {
  conversation: Conversation | null;
  selectedId: string | null;
  onConversationChange: (c: Conversation | null) => void;
  onNew: () => Promise<void> | void;
  onAfterMutation: () => Promise<void> | void;
}

const HINTS = [
  "Fetch records and draft a BRD",
  "Analyse customer data and create requirements",
  "Review evidence and generate a BRD",
];

const supportsStreaming =
  typeof window !== "undefined" &&
  typeof ReadableStream !== "undefined" &&
  typeof TextDecoder !== "undefined";

export function ChatPane({
  conversation,
  selectedId,
  onConversationChange,
  onNew,
  onAfterMutation,
}: Props) {
  const [draft, setDraft] = React.useState("");
  const [sending, setSending] = React.useState(false);
  const [streamingText, setStreamingText] = React.useState("");
  const [pendingUserMsg, setPendingUserMsg] = React.useState<string | null>(null);
  const scrollRef = React.useRef<HTMLDivElement>(null);
  const stickToBottom = React.useRef(true);
  const textareaRef = React.useRef<HTMLTextAreaElement>(null);

  const awaiting =
    conversation?.status === "awaiting_approval" ||
    conversation?.status === "awaiting_brd_confirmation";

  const canSend = !!selectedId && draft.trim().length > 0 && !sending && !awaiting;

  // Autoresize the textarea when the draft changes.
  React.useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    const next = Math.min(el.scrollHeight, 200);
    el.style.height = `${next}px`;
  }, [draft]);

  // Auto-scroll to bottom when conversation changes or new content arrives,
  // but only if the user was already near the bottom.
  const scrollToBottom = React.useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, []);

  React.useEffect(() => {
    if (stickToBottom.current) scrollToBottom();
  }, [conversation?.messages?.length, streamingText, pendingUserMsg, scrollToBottom]);

  const handleScroll = React.useCallback((e: React.UIEvent<HTMLDivElement>) => {
    const el = e.currentTarget;
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    stickToBottom.current = nearBottom;
  }, []);

  const ensureConversation = React.useCallback(async (): Promise<Conversation> => {
    if (conversation) return conversation;
    const c = await api.createConversation();
    onConversationChange(c);
    onAfterMutation();
    return c;
  }, [conversation, onConversationChange, onAfterMutation]);

  const sendRegular = React.useCallback(
    async (convId: string, text: string) => {
      const conv = await api.sendMessage(convId, text);
      onConversationChange(conv);
    },
    [onConversationChange],
  );

  const sendStreaming = React.useCallback(
    async (convId: string, text: string): Promise<boolean> => {
      let tokens = "";
      let streamError: string | null = null;
      let finalConv: Conversation | null = null;

      await sendMessageStream(convId, text, {
        onToken: (t) => {
          tokens += t;
          setStreamingText(tokens);
        },
        onDone: (conv) => {
          finalConv = conv;
        },
        onError: (msg) => {
          streamError = msg;
        },
      });

      setStreamingText("");

      if (streamError && !tokens) return false; // caller will fall back
      if (streamError) throw new Error(streamError);

      if (finalConv) onConversationChange(finalConv);
      else {
        const refreshed = await api.getConversation(convId);
        onConversationChange(refreshed);
      }
      return true;
    },
    [onConversationChange],
  );

  const handleSubmit = React.useCallback(
    async (e?: React.FormEvent) => {
      e?.preventDefault();
      const text = draft.trim();
      if (!text || sending) return;

      setSending(true);
      setDraft("");
      setPendingUserMsg(text);
      stickToBottom.current = true;

      try {
        const conv = await ensureConversation();
        if (supportsStreaming) {
          const ok = await sendStreaming(conv.id, text);
          if (!ok) await sendRegular(conv.id, text);
        } else {
          await sendRegular(conv.id, text);
        }
        onAfterMutation();
      } catch (err) {
        toast.error((err as Error).message);
      } finally {
        setPendingUserMsg(null);
        setStreamingText("");
        setSending(false);
        textareaRef.current?.focus();
      }
    },
    [draft, sending, ensureConversation, sendRegular, sendStreaming, onAfterMutation],
  );

  const handleAction = React.useCallback(
    async (action: "approve" | "reject" | "confirm-evidence" | "reject-evidence") => {
      if (!conversation) return;
      try {
        let updated: Conversation;
        if (action === "approve") updated = await api.approve(conversation.id);
        else if (action === "reject") updated = await api.reject(conversation.id);
        else if (action === "confirm-evidence") updated = await api.confirmEvidence(conversation.id);
        else updated = await api.rejectEvidence(conversation.id);
        onConversationChange(updated);
        onAfterMutation();
      } catch (err) {
        toast.error((err as Error).message);
      }
    },
    [conversation, onConversationChange, onAfterMutation],
  );

  // Empty/welcome state when no conversation is selected.
  if (!conversation) {
    return (
      <>
        <div className="flex flex-1 items-center justify-center overflow-hidden">
          <WelcomeState
            hints={HINTS}
            onHintSelected={async (h) => {
              await onNew();
              setDraft(h);
              setTimeout(() => textareaRef.current?.focus(), 50);
            }}
          />
        </div>
        <Composer
          ref={textareaRef}
          draft={draft}
          setDraft={setDraft}
          onSubmit={handleSubmit}
          canSend={canSend}
          sending={sending}
          disabled={!selectedId}
          placeholder="Start a new BRD to begin…"
        />
      </>
    );
  }

  return (
    <>
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto scrollbar-subtle"
      >
        <div className="mx-auto w-full max-w-3xl px-4 py-6">
          <ChatThread
            messages={conversation.messages}
            pendingUserMsg={pendingUserMsg}
          />

          {sending && !streamingText && <TypingBubble />}
          {streamingText && <StreamingBubble text={streamingText} />}

          {conversation.status === "awaiting_approval" && conversation.review_verdict && (
            <div className="mt-4">
              <ApprovalCard
                verdict={conversation.review_verdict}
                recommendedReject={!!conversation.review_recommended_reject}
                onApprove={() => handleAction("approve")}
                onReject={() => handleAction("reject")}
              />
            </div>
          )}

          {conversation.status === "awaiting_brd_confirmation" &&
            conversation.evidence_summary && (
              <div className="mt-4">
                <EvidenceCard
                  summary={conversation.evidence_summary}
                  onConfirm={() => handleAction("confirm-evidence")}
                  onCancel={() => handleAction("reject-evidence")}
                />
              </div>
            )}
        </div>
      </div>

      <Composer
        ref={textareaRef}
        draft={draft}
        setDraft={setDraft}
        onSubmit={handleSubmit}
        canSend={canSend}
        sending={sending}
        disabled={!selectedId || awaiting}
        placeholder={
          awaiting
            ? conversation.status === "awaiting_brd_confirmation"
              ? "Reviewing evidence — confirm or cancel above…"
              : "Awaiting approval…"
            : "Describe your BRD requirements…"
        }
      />
    </>
  );
}

/* -- Composer ------------------------------------------------------------ */

interface ComposerProps {
  draft: string;
  setDraft: (v: string) => void;
  onSubmit: () => void;
  canSend: boolean;
  sending: boolean;
  disabled: boolean;
  placeholder: string;
}

const Composer = React.forwardRef<HTMLTextAreaElement, ComposerProps>(function Composer(
  { draft, setDraft, onSubmit, canSend, sending, disabled, placeholder },
  ref,
) {
  return (
    <div className="border-t border-border bg-background px-4 py-3">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (canSend) onSubmit();
        }}
        className="mx-auto flex w-full max-w-3xl items-end gap-2"
      >
        <div
          className={cn(
            "flex min-h-[52px] flex-1 items-end gap-2 rounded-xl border border-input bg-background px-3 py-2 shadow-sm transition focus-within:border-ring focus-within:ring-2 focus-within:ring-ring/30",
            disabled && "opacity-60",
          )}
        >
          <Textarea
            ref={ref}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            disabled={disabled}
            maxLength={2000}
            rows={1}
            placeholder={placeholder}
            className="min-h-[28px] flex-1 resize-none border-0 bg-transparent px-0 py-1 shadow-none focus-visible:ring-0 focus-visible:ring-offset-0"
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                if (canSend) onSubmit();
              }
            }}
          />
          <Button
            type="submit"
            size="icon"
            disabled={!canSend}
            aria-label="Send message"
            className="h-8 w-8 shrink-0 rounded-lg"
          >
            {sending ? <Loader2 className="h-4 w-4 animate-spin" /> : <ArrowUp className="h-4 w-4" />}
          </Button>
        </div>
      </form>
      <div className="mx-auto mt-1 max-w-3xl text-center text-[11px] text-muted-foreground">
        Press <kbd className="rounded bg-muted px-1">Enter</kbd> to send,{" "}
        <kbd className="rounded bg-muted px-1">Shift + Enter</kbd> for newline
      </div>
    </div>
  );
});

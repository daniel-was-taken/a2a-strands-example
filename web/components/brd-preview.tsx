"use client";

import * as React from "react";
import { toast } from "sonner";
import { Copy, Check, Download, FileText } from "lucide-react";
import { Button } from "@/components/ui/button";
import { renderMarkdown } from "@/lib/markdown";
import { formatTime } from "@/lib/utils";

interface Props {
  content: string;
  timestamp: string;
}

export function BrdPreview({ content, timestamp }: Props) {
  const [copied, setCopied] = React.useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(content);
      setCopied(true);
      toast.success("BRD copied");
      setTimeout(() => setCopied(false), 1500);
    } catch {
      toast.error("Copy failed");
    }
  };

  const downloadMarkdown = () => {
    const blob = new Blob([content], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `brd-${Date.now()}.md`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  const html = React.useMemo(() => renderMarkdown(content), [content]);

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <div className="flex items-center gap-2">
          <div className="grid h-8 w-8 place-items-center rounded-md bg-primary/10 text-primary">
            <FileText className="h-4 w-4" />
          </div>
          <div className="min-w-0">
            <div className="text-sm font-semibold">BRD preview</div>
            <div className="text-xs text-muted-foreground">
              Generated {formatTime(timestamp)}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-1">
          <Button variant="ghost" size="icon" onClick={copy} aria-label="Copy BRD">
            {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
          </Button>
          <Button variant="ghost" size="icon" onClick={downloadMarkdown} aria-label="Download BRD">
            <Download className="h-4 w-4" />
          </Button>
        </div>
      </div>
      <div className="flex-1 overflow-y-auto bg-background scrollbar-subtle">
        <article className="mx-auto max-w-prose px-5 py-6">
          <div
            className="md-body"
            // eslint-disable-next-line react/no-danger
            dangerouslySetInnerHTML={{ __html: html }}
          />
        </article>
      </div>
    </div>
  );
}

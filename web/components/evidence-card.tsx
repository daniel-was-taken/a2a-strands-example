"use client";

import * as React from "react";
import { ClipboardCheck, Check, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { renderMarkdown } from "@/lib/markdown";

interface Props {
  summary: string;
  onConfirm: () => void;
  onCancel: () => void;
}

export function EvidenceCard({ summary, onConfirm, onCancel }: Props) {
  return (
    <Card className="border-primary/30 bg-primary/[0.02]">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <ClipboardCheck className="h-5 w-5 text-primary" />
          Evidence summary ready
        </CardTitle>
        <CardDescription>Review the findings below, then confirm to draft the BRD.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <Steps current={1} />
        <div className="max-h-[340px] overflow-y-auto rounded-md border border-border bg-background p-3 scrollbar-subtle">
          <div
            className="md-body"
            // eslint-disable-next-line react/no-danger
            dangerouslySetInnerHTML={{ __html: renderMarkdown(summary) }}
          />
        </div>
        <div className="flex flex-wrap gap-2">
          <Button onClick={onConfirm} size="sm">
            <Check className="h-4 w-4" /> Confirm &amp; draft BRD
          </Button>
          <Button onClick={onCancel} size="sm" variant="outline">
            <X className="h-4 w-4" /> Cancel
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function Steps({ current }: { current: 0 | 1 | 2 }) {
  const steps = ["Fetch data", "Review evidence", "Draft BRD"];
  return (
    <ol className="flex items-center gap-2 text-xs">
      {steps.map((label, i) => {
        const done = i < current;
        const active = i === current;
        return (
          <React.Fragment key={label}>
            <li className="flex items-center gap-1.5">
              <span
                className={[
                  "grid h-5 w-5 place-items-center rounded-full text-[11px] font-semibold",
                  done
                    ? "bg-primary text-primary-foreground"
                    : active
                    ? "bg-primary/15 text-primary ring-2 ring-primary/30"
                    : "bg-muted text-muted-foreground",
                ].join(" ")}
              >
                {done ? <Check className="h-3 w-3" /> : i + 1}
              </span>
              <span className={active ? "font-medium" : "text-muted-foreground"}>{label}</span>
            </li>
            {i < steps.length - 1 && <span className="h-px w-4 bg-border" />}
          </React.Fragment>
        );
      })}
    </ol>
  );
}

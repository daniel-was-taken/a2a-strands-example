"use client";

import * as React from "react";
import { AlertTriangle, ShieldCheck, Check, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { renderMarkdown } from "@/lib/markdown";
import { cn } from "@/lib/utils";

interface Props {
  verdict: string;
  recommendedReject: boolean;
  onApprove: () => void;
  onReject: () => void;
}

export function ApprovalCard({ verdict, recommendedReject, onApprove, onReject }: Props) {
  return (
    <Card className={cn(recommendedReject ? "border-destructive/40 bg-destructive/5" : "border-amber-400/40 bg-amber-50/40 dark:bg-amber-950/20")}>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          {recommendedReject ? (
            <AlertTriangle className="h-5 w-5 text-destructive" />
          ) : (
            <ShieldCheck className="h-5 w-5 text-amber-600" />
          )}
          {recommendedReject ? "Safety reviewer recommends rejection" : "Human approval required"}
        </CardTitle>
        <CardDescription>
          {recommendedReject
            ? "The safety reviewer flagged this query as risky. You may override this decision."
            : "The safety reviewer approved this destructive query — your confirmation is needed before execution."}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="rounded-md border border-border bg-background p-3">
          <div className="mb-1 text-xs font-medium text-muted-foreground">Safety verdict</div>
          <div
            className="md-body"
            // eslint-disable-next-line react/no-danger
            dangerouslySetInnerHTML={{ __html: renderMarkdown(verdict) }}
          />
        </div>
        <div className="flex flex-wrap gap-2">
          <Button onClick={onApprove} size="sm">
            <Check className="h-4 w-4" /> Approve &amp; execute
          </Button>
          <Button onClick={onReject} size="sm" variant="outline">
            <X className="h-4 w-4" /> Reject
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

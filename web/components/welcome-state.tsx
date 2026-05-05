"use client";

import * as React from "react";
import { FileText, Sparkles, Database, CheckCircle2 } from "lucide-react";
import { Button } from "@/components/ui/button";

interface Props {
  hints: string[];
  onHintSelected: (hint: string) => void;
}

export function WelcomeState({ hints, onHintSelected }: Props) {
  return (
    <div className="mx-auto max-w-2xl px-6 py-12 text-center">
      <div className="mx-auto grid h-14 w-14 place-items-center rounded-2xl bg-primary text-primary-foreground">
        <FileText className="h-7 w-7" />
      </div>
      <h1 className="mt-5 text-2xl font-semibold tracking-tight">BRD Specialist</h1>
      <p className="mt-2 text-sm text-muted-foreground">
        Describe what you need — I&apos;ll fetch evidence, draft a Business Requirements Document,
        and have another agent review it before handing it back to you.
      </p>

      <div className="mt-8 grid grid-cols-1 gap-2 sm:grid-cols-3">
        <HintCard
          icon={<Database className="h-4 w-4" />}
          title="Fetch & summarise"
          description="Query the database and build an evidence summary"
        />
        <HintCard
          icon={<Sparkles className="h-4 w-4" />}
          title="Draft BRD"
          description="Turn confirmed evidence into a structured document"
        />
        <HintCard
          icon={<CheckCircle2 className="h-4 w-4" />}
          title="Review loop"
          description="Graph reviewer validates before delivery"
        />
      </div>

      <div className="mt-8 flex flex-wrap justify-center gap-2">
        {hints.map((h) => (
          <Button key={h} variant="outline" size="sm" onClick={() => onHintSelected(h)}>
            {h}
          </Button>
        ))}
      </div>
    </div>
  );
}

function HintCard({
  icon,
  title,
  description,
}: {
  icon: React.ReactNode;
  title: string;
  description: string;
}) {
  return (
    <div className="rounded-lg border border-border bg-card p-3 text-left">
      <div className="flex items-center gap-2 text-sm font-medium">
        <span className="grid h-6 w-6 place-items-center rounded-md bg-primary/10 text-primary">
          {icon}
        </span>
        {title}
      </div>
      <p className="mt-1 text-xs text-muted-foreground">{description}</p>
    </div>
  );
}

import { Target } from "lucide-react";

import { ComingSoon } from "@/components/coming-soon";

export default function TargetsPage() {
  return (
    <ComingSoon
      title="Targets"
      description="The clinical AI systems Asclepius attacks, scoped to your organization."
      icon={Target}
      note="Next: a table of targets with health status, model, environment, and open findings — plus a dialog to register a new /chat endpoint."
    />
  );
}

import { Radar } from "lucide-react";

import { ComingSoon } from "@/components/coming-soon";

export default function SweepDetailPage() {
  return (
    <ComingSoon
      title="Live Sweep"
      description="Real-time progress of a running attack sweep, agent by agent."
      icon={Radar}
      note="Next: a streaming activity feed of the Selector → Generator → Judge → Reporter pipeline, with per-variant verdicts updating live."
    />
  );
}

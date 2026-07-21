import { Swords } from "lucide-react";

import { ComingSoon } from "@/components/coming-soon";

export default function LaunchCampaignPage() {
  return (
    <ComingSoon
      title="Launch Campaign"
      description="Configure an attack run: pick a target, choose categories, set variants."
      icon={Swords}
      note="Next: a form to select a target, toggle the five attack categories, choose variants per case, and launch — which will submit a job to the async queue."
    />
  );
}

import Link from "next/link";
import { ShieldPlus } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export default function LoginPage() {
  return (
    <div className="flex min-h-svh flex-1 items-center justify-center p-4">
      <Card className="w-full max-w-sm">
        <CardHeader className="items-center text-center">
          <div className="mb-2 flex size-11 items-center justify-center rounded-xl bg-primary text-primary-foreground">
            <ShieldPlus className="size-6" />
          </div>
          <CardTitle className="text-xl">Sign in to Asclepius</CardTitle>
          <CardDescription>
            Adversarial security for clinical AI
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <div className="flex flex-col gap-2">
            <Label htmlFor="email">Work email</Label>
            <Input id="email" type="email" placeholder="you@hospital.org" />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="password">Password</Label>
            <Input id="password" type="password" placeholder="••••••••" />
          </div>
          <Button
            render={<Link href="/dashboard" />}
            nativeButton={false}
            className="mt-2 w-full"
          >
            Continue
          </Button>
          <p className="text-center text-xs text-muted-foreground">
            Prototype — authentication is mocked for now.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}

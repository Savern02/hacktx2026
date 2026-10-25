"use client";

import { useState } from "react";
import { CheckCircle2, Landmark } from "lucide-react";

import type { UserRead } from "@/app/clientService";
import {
  connectBankAccount,
  fetchProfile,
  saveProfile,
} from "@/components/actions/settings-action";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { CACHE_KEYS, invalidate, setCached, useCached } from "@/lib/data-cache";

type Notice = { tone: "ok" | "error"; text: string } | null;

type ProfileResult = Awaited<ReturnType<typeof fetchProfile>>;

export function SettingsTab() {
  const { result } = useCached(CACHE_KEYS.profile, fetchProfile);
  if (!result) {
    return (
      <div className="grid max-w-lg animate-pulse gap-4" aria-busy="true">
        <span className="h-7 w-32 rounded bg-muted" />
        <span className="h-48 rounded-lg bg-muted" />
        <span className="h-32 rounded-lg bg-muted" />
      </div>
    );
  }
  if (!("data" in result)) {
    return <p className="text-sm text-muted-foreground">{result.message}</p>;
  }
  // Keyed by user so the form starts from the cached profile.
  return <SettingsForm key={result.data.id} profile={result.data} />;
}

function SettingsForm({ profile }: { profile: UserRead }) {
  const [name, setName] = useState(profile.full_name ?? "");
  const [zip, setZip] = useState(profile.zip_code ?? "");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string[]>>({});
  const [saving, setSaving] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [profileNotice, setProfileNotice] = useState<Notice>(null);
  const [bankNotice, setBankNotice] = useState<Notice>(null);

  const setProfile = (update: (p: UserRead) => UserRead) =>
    setCached<ProfileResult>(CACHE_KEYS.profile, (prev) =>
      prev && "data" in prev
        ? { data: update(prev.data) }
        : (prev as ProfileResult),
    );

  const onSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setProfileNotice(null);
    const result = await saveProfile({ full_name: name, zip_code: zip });
    setSaving(false);
    if ("data" in result) {
      if (result.data.zip_code !== profile.zip_code) {
        // A new ZIP means different nearby programs to match against.
        invalidate(CACHE_KEYS.programMatches, CACHE_KEYS.aprImpact);
      }
      setProfile(() => result.data);
      setFieldErrors({});
      setProfileNotice({ tone: "ok", text: "Saved! Equa will remember that." });
    } else {
      setFieldErrors(result.fieldErrors ?? {});
      setProfileNotice({ tone: "error", text: result.message });
    }
  };

  const onConnect = async () => {
    setConnecting(true);
    setBankNotice(null);
    const result = await connectBankAccount();
    setConnecting(false);
    if ("customerId" in result) {
      setProfile((p) => ({ ...p, nessie_customer_id: result.customerId }));
      // New bank, new history: everything financial must reload.
      invalidate(
        CACHE_KEYS.balance,
        CACHE_KEYS.health,
        CACHE_KEYS.aprImpact,
        CACHE_KEYS.lenderRequest,
        CACHE_KEYS.programMatches,
      );
      setBankNotice({
        tone: "ok",
        text: "You're connected! Equa loaded 8 weeks of sample transactions. Check Overview for your money check-up.",
      });
    } else {
      setBankNotice({ tone: "error", text: result.message });
    }
  };

  // Connecting needs a saved name and zip (the backend checks too).
  const profileSaved = Boolean(profile.full_name && profile.zip_code);
  const connected = Boolean(profile.nessie_customer_id);

  return (
    <div className="grid max-w-lg gap-6">
      <h2 className="text-lg font-semibold">Settings</h2>

      <form
        onSubmit={onSave}
        noValidate
        className="grid gap-4 rounded-lg border bg-card p-4"
      >
        <div>
          <h3 className="font-medium">About you</h3>
          <p className="text-sm text-muted-foreground">
            This helps Equa find programs near you.
          </p>
        </div>

        <div className="grid gap-2">
          <Label htmlFor="settings-name">Name</Label>
          <Input
            id="settings-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            autoComplete="name"
            placeholder="Maria Lopez"
            aria-invalid={Boolean(fieldErrors.full_name)}
            aria-describedby={
              fieldErrors.full_name ? "settings-name-error" : undefined
            }
            className="h-11 text-base sm:text-sm"
          />
          {fieldErrors.full_name ? (
            <p id="settings-name-error" className="text-sm text-red-600">
              {fieldErrors.full_name[0]}
            </p>
          ) : null}
        </div>

        <div className="grid gap-2">
          <Label htmlFor="settings-zip">Zip code</Label>
          <Input
            id="settings-zip"
            value={zip}
            onChange={(e) =>
              setZip(e.target.value.replace(/\D/g, "").slice(0, 5))
            }
            inputMode="numeric"
            autoComplete="postal-code"
            placeholder="78702"
            aria-invalid={Boolean(fieldErrors.zip_code)}
            aria-describedby={
              fieldErrors.zip_code ? "settings-zip-error" : undefined
            }
            className="h-11 w-32 text-base sm:text-sm"
          />
          {fieldErrors.zip_code ? (
            <p id="settings-zip-error" className="text-sm text-red-600">
              {fieldErrors.zip_code[0]}
            </p>
          ) : null}
        </div>

        <Button type="submit" disabled={saving} className="h-11 sm:w-fit">
          {saving ? "Saving…" : "Save"}
        </Button>
        {profileNotice ? (
          <p
            role="status"
            className={
              profileNotice.tone === "ok"
                ? "text-sm text-emerald-700 dark:text-emerald-400"
                : "text-sm text-red-600"
            }
          >
            {profileNotice.text}
          </p>
        ) : null}
      </form>

      <section className="grid gap-4 rounded-lg border bg-card p-4">
        <div className="flex items-start gap-3">
          <Landmark
            className="mt-0.5 h-5 w-5 shrink-0 text-muted-foreground"
            aria-hidden="true"
          />
          <div className="min-w-0">
            <h3 className="font-medium">Your bank</h3>
            <p className="text-sm text-muted-foreground">
              {connected
                ? "Equa is connected to your demo bank account."
                : "Connect a demo bank account so Equa can check your spending and find programs for you."}
            </p>
          </div>
        </div>

        {connected ? (
          <p className="flex items-center gap-2 break-all rounded-md bg-muted px-3 py-2 text-xs">
            <CheckCircle2
              className="h-4 w-4 shrink-0 text-emerald-600"
              aria-hidden="true"
            />
            <span>
              Nessie ID:{" "}
              <span className="font-mono">{profile.nessie_customer_id}</span>
            </span>
          </p>
        ) : null}

        <Button
          type="button"
          variant={connected ? "outline" : "default"}
          onClick={onConnect}
          disabled={connecting || !profileSaved}
          className="h-11 sm:w-fit"
        >
          {connecting
            ? "Connecting…"
            : connected
              ? "Reconnect bank"
              : "Connect to bank"}
        </Button>
        {!profileSaved ? (
          <p className="text-sm text-muted-foreground">
            Save your name and zip code first, then you can connect.
          </p>
        ) : null}
        {bankNotice ? (
          <p
            role="status"
            className={
              bankNotice.tone === "ok"
                ? "text-sm text-emerald-700 dark:text-emerald-400"
                : "text-sm text-red-600"
            }
          >
            {bankNotice.text}
          </p>
        ) : null}
      </section>
    </div>
  );
}

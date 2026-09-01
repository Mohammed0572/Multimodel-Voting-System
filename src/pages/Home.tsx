import { Link } from "react-router-dom";
import { Chakra } from "../components/Chakra";
import { useLanguage } from "../context/LanguageContext";
import {
  ShieldCheck,
  Fingerprint,
  ScanFace,
  ArrowRight,
  Lock,
  Languages,
  Eye,
} from "lucide-react";

export default function Home() {
  const { t } = useLanguage();

  return (
    <div className="min-h-screen bg-paper text-ink">
      {/* HERO */}
      <section className="border-b border-hairline">
        <div className="mx-auto grid max-w-7xl gap-16 px-6 py-24 md:grid-cols-[1.1fr_0.9fr] md:py-32">
          <div>
            <div className="mb-6 inline-flex items-center gap-2 rounded-full border border-india-green/30 bg-india-green/5 px-3 py-1 text-xs font-medium text-india-green">
              <span className="size-1.5 rounded-full bg-india-green" />
              Prototype · Configured test network
            </div>
            <h1 className="font-display text-5xl font-semibold leading-[1.05] tracking-tight md:text-7xl">
              {t("home.hero_title1") || "Your vote."}
              <br />
              <span className="text-saffron">
                {t("home.hero_title2") || "Sealed on chain."}
              </span>
            </h1>
            <p className="mt-6 max-w-xl text-lg leading-relaxed text-muted-foreground">
              {t("home.hero_desc") ||
                "Prajatantra is a voting-system prototype that combines voter-ID verification, face authentication, and blockchain-backed ballot recording. Explore the flow, review the source, and connect a wallet only when you are ready to cast a test ballot."}
            </p>
            <div className="mt-10 flex flex-wrap items-center gap-4">
              <Link
                to="/login"
                className="inline-flex items-center gap-2 rounded-md bg-saffron px-6 py-3 text-sm font-semibold text-paper shadow-sm hover:bg-saffron/90"
              >
                {t("home.secure_login") || "Secure Login"}{" "}
                <ArrowRight className="size-4" />
              </Link>
              <Link
                to="/register"
                className="inline-flex items-center gap-2 rounded-md border border-india-blue/30 bg-paper px-6 py-3 text-sm font-semibold text-india-blue shadow-sm hover:bg-india-blue/5"
              >
                Register ID Card
              </Link>
              <a
                href="#how"
                className="inline-flex items-center gap-2 rounded-md border border-ink/20 px-6 py-3 text-sm font-semibold text-ink hover:border-ink"
              >
                {t("home.how_it_works") || "How it works"}
              </a>
            </div>
            <div className="mt-12 flex flex-wrap items-center gap-x-8 gap-y-3 text-xs uppercase tracking-[0.18em] text-muted-foreground">
              <span>Open-source prototype</span>
              <span className="text-hairline">·</span>
              <span>Local or test network</span>
              <span className="text-hairline">·</span>
              <span>Face API integrated</span>
              <span className="text-hairline">·</span>
              <span>MIT licensed</span>
            </div>
          </div>

          <div className="relative flex items-center justify-center">
            <div className="absolute inset-0 -z-10 rounded-full bg-linear-to-br from-saffron/10 via-paper to-india-green/10 blur-3xl" />
            <Chakra size={320} className="text-ashoka" spin />
          </div>
        </div>
      </section>

      {/* MULTIMODAL AUTH */}
      <section className="bg-ink text-paper">
        <div className="mx-auto max-w-7xl px-6 py-24">
          <div className="max-w-2xl">
            <div className="text-xs uppercase tracking-[0.2em] text-saffron">
              Multimodal authentication
            </div>
            <h2 className="mt-3 font-display text-4xl font-semibold text-paper md:text-5xl">
              A clear path from identity to ballot.
            </h2>
            <p className="mt-4 text-paper/70">
              The prototype separates voter identity verification from
              blockchain submission. You provide a voter ID, complete face
              verification, and then use a connected wallet to sign the test
              transaction.
            </p>
          </div>
          <div className="mt-16 grid gap-px overflow-hidden rounded-md border border-paper/10 bg-paper/10 md:grid-cols-2">
            {[
              {
                icon: Fingerprint,
                title: "Voter ID",
                body: "Your voter identifier is normalized before it is sent to the face-authentication service.",
              },
              {
                icon: ScanFace,
                title: "Face Verification",
                body: "A short sequence of camera frames is sent to the configured authentication API for verification.",
              },
            ].map((f) => (
              <div key={f.title} className="bg-ink p-8">
                <f.icon className="size-7 text-saffron" />
                <div className="mt-6 font-display text-xl font-semibold text-paper">
                  {f.title}
                </div>
                <p className="mt-2 text-sm leading-relaxed text-paper/65">
                  {f.body}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* HOW IT WORKS */}
      <section id="how" className="bg-paper-warm">
        <div className="mx-auto max-w-7xl px-6 py-24">
          <div className="flex items-end justify-between gap-8">
            <div>
              <div className="text-xs uppercase tracking-[0.2em] text-india-green">
                How it works
              </div>
              <h2 className="mt-3 font-display text-4xl font-semibold md:text-5xl">
                From verification to immutable record.
              </h2>
            </div>
            <div className="hidden text-right text-sm text-muted-foreground md:block">
              Prototype flow
              <br />
              <span className="font-mono text-ink">4 guided steps</span>
            </div>
          </div>

          <ol className="mt-16 grid gap-10 md:grid-cols-4">
            {[
              {
                n: "01",
                t: "Verify",
                d: "Confirm your EPIC and voter registration.",
              },
              {
                n: "02",
                t: "Authenticate",
                d: "Pass biometric and face verification.",
              },
              {
                n: "03",
                t: "Cast",
                d: "Choose your candidate. Review. Confirm.",
              },
              {
                n: "04",
                t: "Sealed",
                d: "Ballot hashed, signed, and written to chain.",
              },
            ].map((s) => (
              <li key={s.n} className="border-t-2 border-saffron pt-6">
                <div className="font-mono text-xs text-muted-foreground">
                  {s.n}
                </div>
                <div className="mt-2 font-display text-2xl font-semibold">
                  {s.t}
                </div>
                <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
                  {s.d}
                </p>
              </li>
            ))}
          </ol>
        </div>
      </section>

      {/* BLOCKCHAIN TRANSPARENCY */}
      <section id="chain" className="border-t border-hairline">
        <div className="mx-auto max-w-7xl px-6 py-24">
          <div className="grid gap-16 md:grid-cols-[1fr_1.2fr]">
            <div>
              <div className="text-xs uppercase tracking-[0.2em] text-ashoka">
                Public ledger
              </div>
              <h2 className="mt-3 font-display text-4xl font-semibold md:text-5xl">
                Every ballot, publicly verifiable.
              </h2>
              <p className="mt-4 text-muted-foreground">
                In a configured deployment, observers can inspect the
                transaction hash and verify the ballot record on the selected
                network. This demo does not publish a production explorer or
                claim election-grade anonymity.
              </p>
              <a
                href="#chain"
                className="mt-6 inline-flex items-center gap-2 text-sm font-semibold text-ashoka hover:underline"
              >
                View network details <ArrowRight className="size-4" />
              </a>
            </div>
            <div className="rounded-md border border-hairline bg-paper-warm p-8">
              <div className="grid grid-cols-3 gap-6 border-b border-hairline pb-6">
                {[
                  { k: "Network", v: "Configured testnet" },
                  { k: "Receipt", v: "Transaction hash" },
                  { k: "Identity", v: "Separated" },
                ].map((s) => (
                  <div key={s.k}>
                    <div className="text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
                      {s.k}
                    </div>
                    <div className="mt-1 font-display text-2xl font-semibold">
                      {s.v}
                    </div>
                  </div>
                ))}
              </div>
              <div className="mt-6 space-y-3 font-mono text-xs text-muted-foreground">
                <div className="flex justify-between">
                  <span>#4218902</span>
                  <span>0x7a3f…b91c</span>
                  <span>11:42:17</span>
                </div>
                <div className="flex justify-between">
                  <span>#4218901</span>
                  <span>0xc02e…41a8</span>
                  <span>11:42:14</span>
                </div>
                <div className="flex justify-between">
                  <span>#4218900</span>
                  <span>0x9d11…ee03</span>
                  <span>11:42:11</span>
                </div>
                <div className="flex justify-between">
                  <span>#4218899</span>
                  <span>0x1f88…7a2d</span>
                  <span>11:42:08</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* SECURITY & ACCESSIBILITY */}
      <section id="security" className="bg-paper-warm">
        <div className="mx-auto grid max-w-7xl gap-16 px-6 py-24 md:grid-cols-2">
          <div className="rounded-md border border-hairline bg-paper p-10">
            <Lock className="size-8 text-saffron" />
            <h3 className="mt-6 font-display text-2xl font-semibold">
              End-to-end security
            </h3>
            <ul className="mt-4 space-y-3 text-sm text-muted-foreground">
              <li className="flex gap-3">
                <ShieldCheck className="mt-0.5 size-4 text-india-green" />{" "}
                Authentication frames are sent only to the configured API
              </li>
              <li className="flex gap-3">
                <ShieldCheck className="mt-0.5 size-4 text-india-green" /> Voter
                identity hashes are used for duplicate-vote checks
              </li>
              <li className="flex gap-3">
                <ShieldCheck className="mt-0.5 size-4 text-india-green" />{" "}
                Smart-contract rules reject inactive elections and duplicate
                votes
              </li>
            </ul>
          </div>
          <div className="rounded-md border border-hairline bg-paper p-10">
            <Eye className="size-8 text-ashoka" />
            <h3 className="mt-6 font-display text-2xl font-semibold">
              Accessible to every Indian
            </h3>
            <ul className="mt-4 space-y-3 text-sm text-muted-foreground">
              <li className="flex gap-3">
                <Languages className="mt-0.5 size-4 text-ashoka" />{" "}
                Language-ready interface with English and Hindi content paths
              </li>
              <li className="flex gap-3">
                <ShieldCheck className="mt-0.5 size-4 text-ashoka" /> Semantic
                controls, live status messages, and keyboard-friendly flows
              </li>
              <li className="flex gap-3">
                <ShieldCheck className="mt-0.5 size-4 text-ashoka" /> Clear
                recovery guidance for camera, wallet, and network failures
              </li>
            </ul>
          </div>
        </div>
      </section>

      {/* FAQ */}
      <section id="faq" className="border-t border-hairline">
        <div className="mx-auto max-w-4xl px-6 py-24">
          <div className="text-xs uppercase tracking-[0.2em] text-saffron">
            Frequently asked
          </div>
          <h2 className="mt-3 font-display text-4xl font-semibold md:text-5xl">
            Questions, answered.
          </h2>
          <div className="mt-12 divide-y divide-hairline border-y border-hairline">
            {[
              {
                q: "Is my vote anonymous?",
                a: "Yes. Your identity is verified separately from your ballot. Only an encrypted, hashed ballot is written to the chain.",
              },
              {
                q: "What if I lose connectivity mid-vote?",
                a: "Your draft ballot is held locally until you re-authenticate. No partial vote is ever transmitted.",
              },
              {
                q: "Can I verify my vote later?",
                a: "Yes. Use your printed receipt's transaction hash on the public explorer at any time.",
              },
              {
                q: "Who runs the nodes?",
                a: "A federation of constitutional bodies, audited universities and accredited civic-tech non-profits.",
              },
            ].map((f) => (
              <details key={f.q} className="group py-6">
                <summary className="flex cursor-pointer list-none items-center justify-between font-display text-lg font-medium">
                  {f.q}
                  <span className="text-saffron transition group-open:rotate-45">
                    +
                  </span>
                </summary>
                <p className="mt-3 text-sm leading-relaxed text-muted-foreground">
                  {f.a}
                </p>
              </details>
            ))}
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="bg-ink text-paper">
        <div className="tricolor-bar h-0.75 w-full" />
        <div className="mx-auto max-w-7xl px-6 py-16">
          <div className="grid gap-10 md:grid-cols-4">
            <div className="md:col-span-2">
              <div className="flex items-center gap-3">
                <Chakra size={28} className="text-saffron" />
                <span className="font-display text-lg font-semibold">
                  Prajatantra
                </span>
              </div>
              <p className="mt-4 max-w-sm text-sm text-paper/60">
                An open-source voting-system prototype for exploring identity
                verification, wallet signing, and blockchain-backed records.
              </p>
            </div>
            <div className="text-sm">
              <div className="mb-3 text-[10px] uppercase tracking-[0.18em] text-paper/40">
                Citizens
              </div>
              <ul className="space-y-2 text-paper/80">
                <li>
                  <a href="#">Verify a vote</a>
                </li>
                <li>
                  <a href="#">Grievance redressal</a>
                </li>
                <li>
                  <a href="#">Helpline 1950</a>
                </li>
              </ul>
            </div>
            <div className="text-sm">
              <div className="mb-3 text-[10px] uppercase tracking-[0.18em] text-paper/40">
                Transparency
              </div>
              <ul className="space-y-2 text-paper/80">
                <li>
                  <a href="#">Public ledger</a>
                </li>
                <li>
                  <a href="#">Source code</a>
                </li>
                <li>
                  <a href="#">Audit reports</a>
                </li>
              </ul>
            </div>
          </div>
          <div className="mt-12 flex flex-wrap items-center justify-between gap-4 border-t border-paper/10 pt-6 text-xs text-paper/50">
            <div>
              © {new Date().getFullYear()} Government of India · All rights
              reserved
            </div>
            <div className="font-mono">
              {" "}
              chain: configured-network · prototype
            </div>
          </div>
        </div>
      </footer>
    </div>
  );
}

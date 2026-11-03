import { HomeActions } from "@/components/home-actions";
import { HomeHero } from "@/components/home-hero";
import { HOME_SAMPLE } from "@/lib/home-sample";

// Each statement is true by construction and cites its source (UX plan §11.3): consent is
// required at upload (backend/api/voice.py), deleting a voice erases everything made with it
// (backend/services/erasure.py), and the app labels generated speech (footer, result heading).
// No retention figure is published here: it is a server setting, not a promise the page controls.
const PROMISES = [
  {
    title: "Consent first",
    body: "You must confirm you have the right to use a voice before you can clone it.",
  },
  {
    title: "Deleting is complete",
    body: "Delete a voice and everything made with it is erased.",
  },
  {
    title: "Always labelled",
    body: "Generated speech is labelled as AI-generated in the app.",
  },
] as const;

// The product's real sequence (upload or record, then type, then play or download). No claim
// about quality, speed or languages is made here.
const STEPS = [
  {
    title: "Add a sample",
    body: "Upload an audio file, or record with your microphone.",
    sketch: "M4 20h8M20 12v16M28 6v28M36 14v12M44 9v22M52 17v6M60 20h56",
  },
  {
    title: "Type your text",
    body: "Choose the voice and write what it should say.",
    sketch: "M4 12h112M4 20h86M4 28h100",
  },
  {
    title: "Play or download",
    body: "Listen right away, replay it later from your history.",
    sketch: "M4 20h20M30 10v20M38 4v32M46 12v16M54 8v24M62 15v10M70 20h46",
  },
] as const;

export default function HomePage() {
  return (
    <>
      <HomeHero sample={HOME_SAMPLE}>
        <p className="font-mono text-sm text-muted-foreground">Voice cloning, with consent</p>
        <h1
          id="home-title"
          className="mt-4 text-balance text-[2.5rem] font-semibold leading-[1.05] tracking-tight sm:text-6xl"
        >
          Clone a voice. <span className="text-primary">Say anything.</span>
        </h1>
        <p className="mt-5 max-w-xl text-pretty text-lg text-muted-foreground">
          Upload or record 10 to 30 seconds of a voice you have the right to use, then turn any text
          into speech in that voice.
        </p>
        <HomeActions align="start" />
      </HomeHero>

      <ul className="home-reveal grid divide-y divide-border border-y border-border md:grid-cols-3 md:divide-x md:divide-y-0">
        {PROMISES.map((p) => (
          <li key={p.title} className="px-5 py-5">
            <p className="font-medium">{p.title}</p>
            <p className="mt-1 text-sm text-muted-foreground">{p.body}</p>
          </li>
        ))}
      </ul>

      <section aria-labelledby="how" className="mt-16">
        <h2 id="how" className="home-reveal text-2xl font-semibold tracking-tight">
          How it works
        </h2>
        <ol className="mt-6 grid gap-4 sm:grid-cols-3">
          {STEPS.map((s, i) => (
            <li
              key={s.title}
              className="home-reveal rounded-lg border border-border bg-surface p-5"
            >
              <p className="font-mono text-sm text-primary">Step {i + 1}</p>
              <h3 className="mt-3 font-semibold">{s.title}</h3>
              <p className="mt-1 text-sm text-muted-foreground">{s.body}</p>
              <svg
                viewBox="0 0 120 40"
                aria-hidden
                focusable="false"
                className="mt-5 block h-10 w-full"
              >
                <path
                  d={s.sketch}
                  className="fill-none stroke-line"
                  strokeWidth={1.5}
                  strokeLinecap="round"
                />
              </svg>
            </li>
          ))}
        </ol>
      </section>

      <section aria-labelledby="try" className="home-reveal mt-16 pb-6 text-center">
        <h2 id="try" className="text-2xl font-semibold tracking-tight">
          Try it with your own voice.
        </h2>
        <HomeActions closing />
      </section>
    </>
  );
}

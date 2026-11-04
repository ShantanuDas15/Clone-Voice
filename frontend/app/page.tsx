import "./home-experience.css";

import { HomeActions } from "@/components/home-actions";
import { HomeConsentGate } from "@/components/home-consent-gate";
import { HomeEraseDemo } from "@/components/home-erase-demo";
import { HomeHero } from "@/components/home-hero";
import { HomeHowItWorks } from "@/components/home-how-it-works";
import { HOME_SAMPLE } from "@/lib/home-sample";

// Each statement is true by construction and cites its source (UX plan §11.3): consent is
// required at upload (backend/api/voice.py), deleting a voice erases everything made with it
// (backend/services/erasure.py), and the app labels generated speech (footer, result heading).
// No retention figure is published here: it is a server setting, not a promise the page controls.
// The two demos below act those promises out on example data; nothing is sent anywhere.

export default function HomePage() {
  return (
    <div className="hx-root">
      <HomeHero sample={HOME_SAMPLE}>
        <p className="flex items-center gap-2.5 font-mono text-sm text-muted-foreground">
          <span className="hx-dot" />
          Voice cloning, with consent
        </p>
        <h1 id="home-title" className="hx-title">
          <span className="hx-line">
            <span className="hx-word hx-d0">Clone</span> <span className="hx-word hx-d1">a</span>{" "}
            <span className="hx-word hx-d2">voice.</span>
          </span>{" "}
          <span className="hx-line text-primary">
            <span className="hx-word hx-d3">Say</span>{" "}
            <span className="hx-word hx-d4">anything.</span>
          </span>
        </h1>
        <p className="mt-5 max-w-[52ch] text-pretty text-lg text-muted-foreground sm:text-xl">
          Upload or record 10 to 30 seconds of a voice you have the right to use, then turn any text
          into speech in that voice.
        </p>
        <HomeActions align="start" />
      </HomeHero>

      <section aria-labelledby="consent" className="hx-section">
        <div className="hx-split">
          <div>
            <p className="hx-kicker">Consent first</p>
            <h2 id="consent" className="hx-h2">
              A voice is only created once you say you may.
            </h2>
            <p className="hx-sub">
              Try the gate. Until you confirm the right to use the voice, nothing can be created.
            </p>
          </div>
          <HomeConsentGate />
        </div>
      </section>

      <section aria-labelledby="how" className="hx-section">
        <p className="hx-kicker">How it works</p>
        <h2 id="how" className="hx-h2">
          Three steps. Scroll to watch one voice happen.
        </h2>
        <HomeHowItWorks />
      </section>

      <section aria-labelledby="erase" className="hx-section">
        <div className="hx-split hx-split-flip">
          <HomeEraseDemo />
          <div>
            <p className="hx-kicker">Deleting is complete</p>
            <h2 id="erase" className="hx-h2">
              Delete a voice and everything made with it goes too.
            </h2>
            <p className="hx-sub">
              No leftover takes. Generated speech is also labelled as AI-generated in the app.
            </p>
          </div>
        </div>
      </section>

      <section aria-labelledby="try" className="hx-close">
        <h2 id="try" className="hx-h2 mx-auto text-center">
          Try it with your own voice.
        </h2>
        <HomeActions closing />
      </section>
    </div>
  );
}

"""The SV2TTS engine: speaker encoder, Tacotron 2 synthesizer and WaveRNN vocoder.

A thin adapter over ``tts_pipeline``, which still owns model loading, warm-up and the model
functions themselves. Everything is looked up on the module at call time, so the existing
test doubles that patch ``tts_pipeline.vocode`` and friends keep working. Moving the model code
behind the interface is S4.3's job, when a second engine makes it worth doing.
"""

from functools import partial
from typing import Optional

import numpy as np

from backend.core.config import settings
from backend.services import tts_pipeline as pipeline
from backend.services.tts_engine import (NEUTRAL, EngineCapabilities,
                                         StageRunner, SynthesisResult,
                                         SynthesisStyle, TTSEngine,
                                         VoiceConditioning)

# The request schema's text limit (schemas/synthesize.py).
MAX_CHARS = 500

# After a truncated decode the retry splits the text into chunks this many times smaller
# for each earlier truncation, never below the floor (a chunk of a few words always fits in
# the frame cap). SPEECH_QUALITY_STUDY.md, S3.4b.
RETRY_CHUNK_DIVISOR = 2
MIN_RETRY_CHUNK_CHARS = 20


def retry_chunk_chars(truncation_retries: int) -> Optional[int]:
    """Chunk size for a retry after ``truncation_retries`` truncated attempts (None: default)."""
    if truncation_retries <= 0:
        return None
    return max(
        MIN_RETRY_CHUNK_CHARS,
        settings.TTS_CHUNK_MAX_CHARS // (RETRY_CHUNK_DIVISOR**truncation_retries),
    )


class Sv2ttsEngine(TTSEngine):
    """Real-Time Voice Cloning (SV2TTS): neutral read speech at 16 kHz."""

    name = "sv2tts"
    version = "1"

    def capabilities(self) -> EngineCapabilities:
        """SV2TTS speaks 16 kHz, neutral only."""
        return EngineCapabilities(
            name=self.name,
            version=self.version,
            sample_rate=settings.VOCODER_SAMPLE_RATE,
            max_chars=MAX_CHARS,
            emotions=(NEUTRAL,),
            seedable=True,
        )

    def health(self, expected_device: Optional[str] = None) -> dict:
        """Delegate to the pipeline's model health report."""
        return pipeline.get_model_health(expected_device)

    def conditioning_from_array(self, embedding: np.ndarray) -> VoiceConditioning:
        """A stored profile embedding is the 256-d speaker vector."""
        return VoiceConditioning(self.name, self.version, embedding)

    async def prepare_voice(self, audio: np.ndarray) -> VoiceConditioning:
        """Embed the audio with the speaker encoder, under the inference slot."""
        embedding = await pipeline.embed_speaker_async(audio)
        return self.conditioning_from_array(embedding)

    async def synthesize(
        self,
        text: str,
        conditioning: VoiceConditioning,
        style: Optional[SynthesisStyle],
        *,
        run_stage: StageRunner,
        truncation_retries: int = 0,
        seed: Optional[int] = None,
    ) -> SynthesisResult:
        """Synthesize mel frames, then vocode them, each as its own timed stage."""
        self.check_request(conditioning, style)
        chunk_chars = retry_chunk_chars(truncation_retries)
        # Only a seeded request changes the call, so existing doubles of the stage still match.
        stage_fn = (
            pipeline._synthesize_counting_truncation
            if seed is None
            else partial(pipeline._synthesize_counting_truncation, seed=seed)
        )
        mel, truncated = await run_stage(
            "synthesizer",
            stage_fn,
            text,
            conditioning.embedding,
            *(() if chunk_chars is None else (chunk_chars,)),
        )
        waveform = await run_stage("vocoder", pipeline.vocode, mel)
        return SynthesisResult(waveform, settings.VOCODER_SAMPLE_RATE, truncated)

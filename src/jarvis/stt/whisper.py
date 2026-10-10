"""Speech-to-text with faster-whisper on the GPU (ADR-015)."""

import asyncio
import logging
import os
import threading
import time
from typing import Any

import numpy as np

from jarvis.audio.clip import Samples
from jarvis.audio.vad import SAMPLE_RATE
from jarvis.config import SttConfig
from jarvis.i18n import Language
from jarvis.stt.base import Transcript
from jarvis.stt.cuda import register_nvidia_dlls
from jarvis.stt.language import choose_language

log = logging.getLogger(__name__)

CPU_FALLBACK_COMPUTE_TYPE = "int8"


class WhisperStt:
    def __init__(self, config: SttConfig) -> None:
        self._config = config
        self._model: Any = None
        # CTranslate2 models are not meant to run two transcriptions at once.
        self._lock = threading.Lock()

    def load(self) -> None:
        """Load the model (blocking, several seconds; downloads it on first use)."""
        # The Hugging Face cache works without symlinks on Windows; silence its warning.
        os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
        register_nvidia_dlls()
        from faster_whisper import WhisperModel

        config = self._config
        start = time.perf_counter()
        try:
            model = WhisperModel(
                config.model, device=config.device, compute_type=config.compute_type
            )
            self._warm_up(model)
        except (RuntimeError, ValueError) as exc:
            if config.device == "cpu":
                raise
            # Missing CUDA libraries only surface on the first inference, hence the warm-up.
            log.warning("GPU unavailable (%s); falling back to the CPU, which is slower", exc)
            model = WhisperModel(config.model, device="cpu", compute_type=CPU_FALLBACK_COMPUTE_TYPE)
            self._warm_up(model)
        self._model = model
        log.info("Speech model %s ready in %.1f s", config.model, time.perf_counter() - start)

    async def transcribe(self, audio: Samples, previous_language: Language) -> Transcript:
        return await asyncio.to_thread(self._transcribe, audio, previous_language)

    def _transcribe(self, audio: Samples, previous_language: Language) -> Transcript:
        if self._model is None:
            raise RuntimeError("Speech model not loaded")
        with self._lock:
            # With language=None, Whisper detects the language eagerly and reuses that
            # encoder pass for transcription; the text itself is decoded lazily, when the
            # segments are read. So the detection can be checked before paying for decoding.
            segments, info = self._run(audio, language=None)
            choice = choose_language(
                info.all_language_probs or [],
                len(audio) / SAMPLE_RATE,
                previous_language,
                self._config,
            )
            if info.language != choice.language.value:
                # Whisper picked another language (or was unsure): decode in the chosen one.
                segments, _ = self._run(audio, language=choice.language.value)
            text = " ".join(segment.text.strip() for segment in segments).strip()
        log.debug(
            "Language %s (confidence %.2f, %s)",
            choice.language,
            choice.confidence,
            "detected" if choice.detected else "kept from previous turn",
        )
        return Transcript(text, choice.language, choice.confidence)

    def _run(self, audio: Samples, language: str | None) -> Any:
        """(segments, info) from faster-whisper, which ships no type information."""
        return self._model.transcribe(
            audio,
            language=language,
            beam_size=self._config.beam_size,
            vad_filter=False,  # the audio was already cut by our own VAD
            condition_on_previous_text=False,
        )

    @staticmethod
    def _warm_up(model: Any) -> None:
        """Run detection and decoding once, so the first real request is not slower."""
        segments, _ = model.transcribe(np.zeros(SAMPLE_RATE, dtype=np.float32))
        list(segments)

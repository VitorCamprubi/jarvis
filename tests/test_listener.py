import asyncio
from pathlib import Path

import numpy as np
import pytest
import soundfile
from audio_fakes import FakeInputStream, ScriptedVad, frames, microphone_for

from jarvis.audio.clip import Samples
from jarvis.audio.listener import MicrophoneError, MicrophoneListener, Utterance, Vad
from jarvis.audio.microphone import Microphone
from jarvis.audio.vad import FRAME_SAMPLES, SAMPLE_RATE, SileroVad
from jarvis.config import VadConfig

FIXTURE = Path(__file__).parent / "fixtures" / "speech_pt.wav"
CONFIG = VadConfig(
    threshold=0.5,
    min_speech_level_dbfs=-45.0,
    silence_ms=320,
    no_speech_timeout_s=1.0,
    max_utterance_s=5.0,
    pre_roll_ms=128,
)


def listen(audio_frames: list[Samples], vad: Vad) -> tuple[Utterance | None, FakeInputStream]:
    async def scenario() -> tuple[Utterance | None, FakeInputStream]:
        microphone, streams = microphone_for(audio_frames)
        utterance = await MicrophoneListener(CONFIG, vad, microphone).listen()
        assert not microphone.is_open  # closed again: nobody else listens
        return utterance, streams[0]

    return asyncio.run(scenario())


def test_records_speech_with_pre_roll_and_trims_trailing_silence() -> None:
    probabilities = [0.0] * 10 + [0.9] * 20 + [0.0] * 30
    utterance, stream = listen(frames(60), ScriptedVad(probabilities))

    assert utterance is not None
    # 4 pre-roll frames + 20 speech frames + 200 ms (6 frames) of trailing silence
    assert len(utterance.audio) == (4 + 20 + 6) * FRAME_SAMPLES
    assert stream.settings["samplerate"] == SAMPLE_RATE
    assert stream.settings["device"] == 3
    assert stream.closed


def test_returns_none_when_nothing_is_said() -> None:
    utterance, _ = listen(frames(100), ScriptedVad([0.0]))

    assert utterance is None


def test_real_speech_is_cut_after_the_silence_window() -> None:
    speech, _ = soundfile.read(FIXTURE, dtype="float32")
    silence = np.zeros(SAMPLE_RATE * 2, dtype=np.float32)
    audio = np.concatenate([silence[:4800], speech, silence])
    audio_frames = list(
        audio[: len(audio) // FRAME_SAMPLES * FRAME_SAMPLES].reshape(-1, FRAME_SAMPLES)
    )

    utterance, _ = listen(audio_frames, SileroVad())

    assert utterance is not None
    assert 1.2 < utterance.duration_s < 2.5  # the 1.5 s phrase, give or take VAD edges


def test_audio_from_before_the_wake_word_is_kept() -> None:
    """Woken by voice, the request already under way is part of the utterance."""

    async def scenario() -> Utterance | None:
        microphone, streams = microphone_for(frames(30) + frames(40, 0.0), pause_after=30)
        watch = microphone.subscribe()  # the wake word keeps the microphone open
        await asyncio.to_thread(streams[0].paused.wait)  # 30 frames of speech went by
        vad = ScriptedVad([0.9] * 30 + [0.0] * 40)
        listening = asyncio.create_task(
            MicrophoneListener(CONFIG, vad, microphone).listen(
                backlog_s=30 * FRAME_SAMPLES / SAMPLE_RATE
            )
        )
        await asyncio.sleep(0)  # subscribed, with the backlog
        streams[0].resume()
        utterance = await listening
        microphone.unsubscribe(watch)
        return utterance

    utterance = asyncio.run(scenario())

    assert utterance is not None
    assert len(utterance.audio) == (30 + 6) * FRAME_SAMPLES  # backlog + 200 ms of silence


def test_a_microphone_that_cannot_open_raises_a_clear_error() -> None:
    def broken(**settings: object) -> object:
        raise OSError("device unavailable")

    async def scenario() -> None:
        microphone = Microphone(lambda: None, history_s=1, stream_factory=broken)
        await MicrophoneListener(CONFIG, ScriptedVad([0.0]), microphone).listen()

    with pytest.raises(MicrophoneError, match="device unavailable"):
        asyncio.run(scenario())

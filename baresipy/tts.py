"""Pluggable TTS backend for baresipy.

baresipy no longer depends on ResponsiveVoice. Instead, any object exposing
the OpenVoiceOS Plugin Manager (OPM) TTS interface -
``get_tts(sentence, wav_file) -> (wav_file, phonemes)`` - can be passed in
via the ``tts`` kwarg of ``BareSIP``.

If ``ovos-plugin-manager`` (and a TTS plugin) is installed, a default engine
can be created lazily via :func:`get_default_tts`.
"""
from typing import Optional

from baresipy.utils.log import LOG


def get_default_tts() -> Optional[object]:
    """Lazily create a default OVOS TTS plugin instance.

    Returns None (and logs a warning) if ovos-plugin-manager or the default
    TTS plugin are not installed. Install the ``ovos`` extra to enable this:
    ``pip install baresipy[ovos]``
    """
    try:
        from ovos_plugin_manager.tts import OVOSTTSFactory
        return OVOSTTSFactory.create({"module": "ovos-tts-plugin-phoonnx"})
    except Exception as e:
        LOG.warning(f"could not create default TTS engine: {e}. "
                     f"pass tts= or install baresipy[ovos]")
        return None

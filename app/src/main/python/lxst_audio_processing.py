# SPDX-License-Identifier: 0BSD
"""Preserve LXST speech filters when capture comes from Android or a browser."""
import math


def prepare_capture_filters(filters, *, default_max_gain_db=None, echo_before_gain=False):
    if not filters:
        return []
    from LXST.Filters import AGC

    prepared = list(filters or [])
    for audio_filter in prepared:
        if isinstance(audio_filter, AGC):
            # LXST 0.5.4 treats amplitude dB values as power ratios. Correct
            # only those legacy values, preserving explicitly customized gains.
            for level_name, gain_name in (("target_level", "target_linear"),
                                           ("max_gain_db", "max_gain_linear")):
                level = getattr(audio_filter, level_name)
                if math.isclose(getattr(audio_filter, gain_name), 10 ** (level / 10)):
                    setattr(audio_filter, gain_name, 10 ** (level / 20))
            if (default_max_gain_db is not None
                    and audio_filter.max_gain_db == 12.0
                    and math.isclose(audio_filter.max_gain_linear, 10 ** (12 / 20))):
                audio_filter.max_gain_db = default_max_gain_db
                audio_filter.max_gain_linear = 10 ** (default_max_gain_db / 20)
    if echo_before_gain:
        # Let the echo filter compare the microphone with the speaker
        # reference before automatic gain changes the microphone level.
        prepared.sort(key=lambda audio_filter: isinstance(audio_filter, AGC))
    return prepared

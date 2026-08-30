import os
import tempfile
import unittest
import wave

from pydub.generators import Sine

import baresipy


def make_sine_wav(path, duration_ms=1000, frame_rate=44100, channels=1):
    tone = Sine(440).to_audio_segment(duration=duration_ms)
    tone = tone.set_frame_rate(frame_rate).set_channels(channels)
    tone.export(path, format="wav")
    return path


class TestConvertAudio(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.input_wav = os.path.join(self.tmpdir.name, "in.wav")
        make_sine_wav(self.input_wav, duration_ms=1000,
                      frame_rate=44100, channels=1)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_default_params(self):
        outfile = os.path.join(self.tmpdir.name, "out.wav")
        result_path, duration = baresipy.BareSIP.convert_audio(
            self.input_wav, outfile=outfile)
        self.assertEqual(result_path, outfile)
        self.assertTrue(os.path.isfile(outfile))
        self.assertGreaterEqual(duration, 3.0)

        with wave.open(outfile, "rb") as w:
            self.assertEqual(w.getframerate(), 48000)
            self.assertEqual(w.getnchannels(), 2)

    def test_custom_params(self):
        outfile = os.path.join(self.tmpdir.name, "out16k.wav")
        result_path, duration = baresipy.BareSIP.convert_audio(
            self.input_wav, outfile=outfile,
            frame_rate=16000, channels=1, min_duration_s=1.0)
        self.assertTrue(os.path.isfile(outfile))
        self.assertGreaterEqual(duration, 1.0)

        with wave.open(outfile, "rb") as w:
            self.assertEqual(w.getframerate(), 16000)
            self.assertEqual(w.getnchannels(), 1)

    def test_min_duration_padding(self):
        outfile = os.path.join(self.tmpdir.name, "out_pad.wav")
        # 1s input, silence padding added till reaching 4s minimum
        result_path, duration = baresipy.BareSIP.convert_audio(
            self.input_wav, outfile=outfile, min_duration_s=4.0)
        self.assertGreaterEqual(duration, 4.0)


if __name__ == "__main__":
    unittest.main()

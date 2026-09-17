import math
import struct
import unittest

from baresipy.audio import resample_pcm16


def make_sine(n_frames, channels, rate, freq=440.0, amplitude=10000):
    samples = []
    for i in range(n_frames):
        val = int(amplitude * math.sin(2 * math.pi * freq * i / rate))
        for _ in range(channels):
            samples.append(val)
    return struct.pack("<%dh" % len(samples), *samples)


def count_zero_crossings(data):
    (n,) = (len(data) // 2,)
    samples = struct.unpack("<%dh" % n, data)
    crossings = 0
    for i in range(1, len(samples)):
        if (samples[i - 1] < 0) != (samples[i] < 0):
            crossings += 1
    return crossings


class TestResamplePcm16(unittest.TestCase):
    def test_length_approx_ratio(self):
        src_rate, dst_rate, channels = 48000, 16000, 2
        n_frames = 4800
        data = make_sine(n_frames, channels, src_rate)
        out = resample_pcm16(data, src_rate, channels, dst_rate=dst_rate)
        out_frames = len(out) // 2
        expected = n_frames // 3  # only sample-rate ratio downsamples frames
        self.assertLessEqual(abs(out_frames - expected), 1)

    def test_constant_signal_stays_constant(self):
        src_rate, dst_rate, channels = 48000, 16000, 2
        n_frames = 1000
        value = 1234
        samples = [value] * (n_frames * channels)
        data = struct.pack("<%dh" % len(samples), *samples)
        out = resample_pcm16(data, src_rate, channels, dst_rate=dst_rate)
        out_samples = struct.unpack("<%dh" % (len(out) // 2), out)
        for s in out_samples:
            self.assertEqual(s, value)

    def test_sine_frequency_roughly_preserved(self):
        src_rate, dst_rate, channels = 48000, 16000, 1
        freq = 440.0
        duration_s = 0.5
        n_frames = int(src_rate * duration_s)
        data = make_sine(n_frames, channels, src_rate, freq=freq)
        out = resample_pcm16(data, src_rate, channels, dst_rate=dst_rate)

        # zero-crossing count is a function of frequency * duration, and is
        # independent of sample rate as long as both rates are well above
        # Nyquist for `freq` - so it should be roughly preserved across
        # resampling (same represented duration, same tone).
        src_crossings = count_zero_crossings(data)
        dst_crossings = count_zero_crossings(out)

        self.assertAlmostEqual(
            dst_crossings, src_crossings,
            delta=max(2, src_crossings * 0.10))


if __name__ == "__main__":
    unittest.main()

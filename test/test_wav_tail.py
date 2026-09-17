import os
import tempfile
import threading
import time
import unittest
import wave

from baresipy.audio import WavTailReader


class TestWavTailReader(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.path = os.path.join(self.tmpdir, "dump-test-dec.wav")

    def test_reads_header_and_growing_data(self):
        rate = 8000
        channels = 1
        width = 2
        frame1 = b"\x01\x00" * 100
        frame2 = b"\x02\x00" * 100

        def writer():
            wf = wave.open(self.path, "wb")
            wf.setnchannels(channels)
            wf.setsampwidth(width)
            wf.setframerate(rate)
            wf.writeframes(frame1)
            wf._file.flush()
            time.sleep(0.3)
            wf.writeframes(frame2)
            wf._file.flush()
            time.sleep(0.5)
            wf.close()

        t = threading.Thread(target=writer)
        t.start()

        try:
            reader = WavTailReader(self.path, timeout=5.0)
            self.assertEqual(reader.sample_rate, rate)
            self.assertEqual(reader.channels, channels)
            self.assertEqual(reader.sample_width, width)

            data = reader.read(len(frame1), timeout=5.0)
            self.assertEqual(data, frame1)

            data2 = reader.read(len(frame2), timeout=5.0)
            self.assertEqual(data2, frame2)

            reader.close()
        finally:
            t.join()

    def test_read_timeout_returns_empty_when_no_data(self):
        wf = wave.open(self.path, "wb")
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(8000)
        wf.writeframes(b"\x00\x00" * 10)
        wf.close()

        reader = WavTailReader(self.path, timeout=5.0)
        # ask for way more data than exists, with a short timeout
        start = time.time()
        data = reader.read(100000, timeout=0.3)
        elapsed = time.time() - start
        self.assertLess(len(data), 100000)
        self.assertLess(elapsed, 2.0)


if __name__ == "__main__":
    unittest.main()

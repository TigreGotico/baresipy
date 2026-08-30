from time import sleep, time as _time
import glob
import pexpect
from opentone import ToneGenerator
from pydub import AudioSegment
import tempfile
import logging
import subprocess
import threading
from threading import Thread
from typing import List, Optional, Tuple, Union
from baresipy.utils.log import LOG
from baresipy.tts import get_default_tts
from baresipy.config import render_config, ensure_sndfile_recording
from baresipy.audio import WavTailReader
from baresipy.call import CallInfo, parse_sip_uri
from os.path import expanduser, join, isfile, isdir, getmtime
from os import makedirs
from shutil import which
import signal
import re


def _find_baresip_binary() -> str:
    """Resolve the baresip executable to run.

    Prefers the self-contained binary shipped by the optional
    ``baresip-binary`` package (no system ``baresip`` install required);
    falls back to a system-installed ``baresip`` on PATH.
    """
    try:
        from baresip_binary import BARESIP_BIN
        return BARESIP_BIN
    except ImportError:
        return which("baresip") or "baresip"

logging.getLogger("urllib3.connectionpool").setLevel("WARN")
logging.getLogger("pydub.converter").setLevel("WARN")


class BareSIP(Thread):
    def __init__(self, user: Optional[str] = None, pwd: Optional[str] = None,
                 gateway: Optional[str] = None, transport: str = "udp",
                 tts: Optional[object] = None, debug: bool = False,
                 block: bool = True, config_path: Optional[str] = None,
                 sounds_path: Optional[Union[str, bool]] = None,
                 autostart: bool = True,
                 login_options: Optional[str] = None,
                 headless: bool = False,
                 audio_driver: str = "alsa,default",
                 record_rx: bool = False,
                 recording_path: Optional[str] = None,
                 max_login_retries: int = 0,
                 login_retry_delay: float = 15.0,
                 media_encryption: Optional[str] = None,
                 sip_cafile: Optional[str] = None,
                 audio_frame_rate: int = 48000,
                 audio_channels: int = 2):
        """
        :param max_login_retries: if > 0, retry registration this many
            times (with `login_retry_delay` seconds between attempts)
            before giving up and calling `handle_login_failure()` (which
            quits). 0 (default) preserves the original behaviour of
            quitting immediately on the first registration failure.
        :param login_retry_delay: seconds to wait between registration
            retries, only used when `max_login_retries > 0`.
        :param media_encryption: one of "srtp"/"srtp-mand"/"srtp-mandf"/
            "dtls_srtp". If set, appended to the SIP account line as
            `;mediaenc=<value>` and implies `enable_srtp=True` when
            rendering the config.
        :param sip_cafile: path to a CA bundle used to verify the SIP
            server certificate. Required for real verification when
            `transport="tls"` is used.
        :param audio_frame_rate: frame rate (Hz) used when converting
            audio for playback/transmission via `convert_audio`.
            Defaults to 48000 (previous hardcoded behaviour). Some
            backends reject 48kHz aufile playback (#16, #18) and need
            a different value.
        :param audio_channels: channel count used when converting audio
            for playback/transmission via `convert_audio`. Defaults to
            2 (previous hardcoded behaviour). Some backends reject
            stereo aufile playback (#16, #18) and need mono (1).
        """
        config_path = config_path or join("~", ".baresipy")
        self.config_path = expanduser(config_path)
        if not isdir(self.config_path):
            makedirs(self.config_path)

        self._default_ausrc = "ausine,400" if headless else audio_driver

        self.record_rx = record_rx
        self.recording_path = None
        if record_rx:
            self.recording_path = recording_path or \
                tempfile.mkdtemp(dir=tempfile.gettempdir())
            if not isdir(self.recording_path):
                makedirs(self.recording_path)

        if isfile(join(self.config_path, "config")):
            with open(join(self.config_path, "config"), "r") as f:
                self.config = f.read()
            LOG.info("config loaded from " + self.config_path + "/config")
            self.updated_config = False
        else:
            # baresipy's bundled template is still shaped for a much older
            # baresip: jitter_buffer_delay, zrtp.so, and module_path pointing at
            # the apt location /usr/lib/baresip/modules. On an Elixir device,
            # where baresip is built from source and installs its modules under
            # /usr/local, a config written from it loads no modules at all - so
            # the phone comes up with no codecs and no audio driver, and nothing
            # in the log says why.
            #
            # This should never be reached: configserv writes this file, and
            # has baresip write itself a fresh one first if there is none. If it
            # IS reached, the missing config is the thing to fix.
            LOG.error(
                "No config at %s - falling back to baresipy's bundled template, "
                "which targets an older baresip. Save the settings once from "
                "configserv to have the real config written.",
                join(self.config_path, "config"))
            self.config = render_config(
                audio_driver=audio_driver, headless=headless,
                sip_cafile=sip_cafile,
                enable_srtp=bool(media_encryption))
            self.updated_config = True

        self._original_config = str(self.config)

        if record_rx:
            # ensure the two sndfile config lines are present regardless of
            # whether self.config came from render_config or an existing
            # user-provided config file
            self.config = ensure_sndfile_recording(self.config,
                                                     self.recording_path)
            self.updated_config = True

        if sounds_path is not None and "#audio_path" in self.config:
            self.updated_config = True
            if sounds_path is False:
                # sounds disabled
                self.config = self.config.replace(
                    "#audio_path		/usr/share/baresip",
                    "audio_path		/dont/load")
            elif isdir(sounds_path):
                self.config = self.config.replace(
                    "#audio_path		/usr/share/baresip",
                    "audio_path		" + sounds_path)

        if self.updated_config:
            with open(join(self.config_path, "config.bak"), "w") as f:
                f.write(self._original_config)

            LOG.info("saving config")
            with open(join(self.config_path, "config"), "w") as f:
                f.write(self.config)

        self.debug = debug
        self.user = user
        self.pwd = pwd
        self.gateway = gateway
        self.transport = transport
        self.tts = tts
        self.media_encryption = media_encryption
        self.sip_cafile = sip_cafile
        self._login = None
        if self.gateway:
            self._login = "sip:{u}@{g};transport={t};auth_pass={p}".format(
                u=self.user, p=self.pwd, g=self.gateway, t=self.transport)
            if login_options:
                self._login += ";{o}".format(o=login_options)
            if media_encryption:
                self._login += ";mediaenc={e}".format(e=media_encryption)
        self._prev_output = ""
        self._local_ua_added = False
        self.running = False
        self.ready = False
        self.mic_muted = False
        self.abort = False
        self.current_call = None
        self._call_status = None
        self.audio = None
        self._ts = None
        self._block_until_ready = block
        self._tx_interrupted = False
        self.current_call_info: Optional[CallInfo] = None
        self.call_history: List[CallInfo] = []
        self.max_login_retries = max_login_retries
        self.login_retry_delay = login_retry_delay
        self._login_retry_count = 0
        self.audio_frame_rate = audio_frame_rate
        self.audio_channels = audio_channels
        self.baresip = None
        self.startBareSIPSubProcess()
        super().__init__()
        if autostart:
            self.start()

    def start(self) -> None:
        """Start the event loop thread, optionally blocking until ready."""
        super().start()
        if self._block_until_ready:
            self.wait_until_ready()

    # properties
    @property
    def call_established(self) -> bool:
        return self.call_status == "ESTABLISHED"

    @property
    def call_status(self) -> str:
        return self._call_status or "DISCONNECTED"

    # actions
    def do_command(self, action: str) -> None:
        if self.ready:
            action = str(action)
            self.baresip.sendline(action)
        else:
            LOG.warning(action + " not executed!")
            LOG.error("NOT READY! please wait")

    def login(self) -> None:
        if not self._login:
            # registrar-less mode still needs a local (non-registering)
            # user agent, or baresip can not place or receive calls
            if self._local_ua_added:
                return
            self._local_ua_added = True
            local_aor = "sip:{u}@0.0.0.0;regint=0".format(
                u=self.user or "baresipy")
            LOG.info("Adding local account: " + local_aor)
            self.baresip.sendline("/uanew " + local_aor)
            return
        LOG.info("Adding account: " + str(self.user))
        self.baresip.sendline("/uanew " + self._login)

    def call(self, number: str) -> None:
        if number.startswith("sip:"):
            target = number
        elif self.gateway:
            target = "sip:{n}@{g}".format(n=number, g=self.gateway)
        else:
            raise ValueError(
                "no gateway configured, `number` must be a full SIP URI "
                "(sip:...)")
        LOG.info("Dialling: " + target)
        self.do_command("/dial " + target)

    def hang(self) -> None:
        if self.current_call:
            LOG.info("Hanging: " + self.current_call)
            self.do_command("/hangup")
            self.current_call = None
            self._call_status = None
        else:
            LOG.error("No active call to hang")

    def hold(self) -> None:
        if self.current_call:
            LOG.info("Holding: " + self.current_call)
            self.do_command("/hold")
        else:
            LOG.error("No active call to hold")

    def resume(self) -> None:
        if self.current_call:
            LOG.info("Resuming " + self.current_call)
            self.do_command("/resume")
        else:
            LOG.error("No active call to resume")

    def transfer(self, uri: str) -> None:
        """Transfer (blind/attended-lite) the active call to `uri` using
        baresip's `menu` module dynamic `/transfer` command (SIP REFER)."""
        if not self.current_call:
            LOG.error("No active call to transfer")
            return
        LOG.info("Transferring call to: " + uri)
        self.do_command("/transfer " + uri)

    def handle_transfer_ok(self) -> None:
        LOG.info("Call transfer succeeded")

    def handle_transfer_failed(self, reason: str) -> None:
        LOG.warning("Call transfer failed: " + reason)

    def mute_mic(self) -> None:
        if not self.call_established:
            LOG.error("Can not mute microphone while not in a call")
            return
        if not self.mic_muted:
            LOG.info("Muting mic")
            self.do_command("/mute")
        else:
            LOG.info("Mic already muted")

    def unmute_mic(self) -> None:
        if not self.call_established:
            LOG.error("Can not unmute microphone while not in a call")
            return
        if self.mic_muted:
            LOG.info("Unmuting mic")
            self.do_command("/mute")
        else:
            LOG.info("Mic already unmuted")

    def accept_call(self) -> None:
        self.do_command("/accept")
        status = "ESTABLISHED"
        self.handle_call_status(status)
        self._call_status = status

    def get_rx_wav(self, timeout: float = 10.0) -> Optional[str]:
        """Return the path to the newest received-audio wav recording
        (`*-dec.wav`, ie what the peer said) written by baresip's sndfile
        module, waiting up to `timeout` seconds for one to appear.

        Requires `record_rx=True` to have been set at construction time.
        """
        if not self.recording_path:
            LOG.error("recording not enabled, pass record_rx=True")
            return None
        pattern = join(self.recording_path, "*-dec.wav")
        deadline = None
        while True:
            matches = glob.glob(pattern)
            if matches:
                return max(matches, key=getmtime)
            if deadline is None:
                deadline = _time() + timeout
            if _time() >= deadline:
                return None
            sleep(0.1)

    def get_rx_stream(self, timeout: float = 10.0) -> Optional[WavTailReader]:
        """Return a `WavTailReader` tailing the newest received-audio wav
        recording, or None if no such recording appeared within `timeout`
        seconds.
        """
        wav = self.get_rx_wav(timeout)
        if not wav:
            return None
        try:
            return WavTailReader(wav, timeout=timeout)
        except TimeoutError:
            return None

    def list_calls(self) -> None:
        self.do_command("/listcalls")

    def check_call_status(self) -> str:
        self.do_command("/callstat")
        sleep(0.1)
        return self.call_status

    def quit(self) -> None:
        if not self.running and self.abort:
            # already shut down
            return
        if self.updated_config:
            LOG.info("restoring original config")
            with open(join(self.config_path, "config"), "w") as f:
                f.write(self._original_config)
        LOG.info("Exiting")
        if self.running:
            if self.current_call:
                self.hang()
        self.running = False
        self.current_call = None
        self._call_status = None
        self.abort = True
        self.killBareSIPSubProcess()

    def logout(self) -> None:
        """Remove every account from the running baresip.

        The phone re-registers by building a fresh account rather than by
        waiting for baresip to retry, so the old one has to go first or
        baresip ends up with two.
        """
        LOG.info("Removing account: " + str(self.user))
        self.baresip.sendline("/uadelall")

    def killBareSIPSubProcess(self) -> None:
        """Stop the baresip process, leaving this object able to start another.

        Setting self.baresip back to None is what tells run() to spawn a
        replacement. Every step is guarded because this is called on the way
        out of an already-failing situation as often as not.
        """
        if self.baresip is not None and self.baresip.isalive():
            LOG.info("Killing BareSip process")
            try:
                self.baresip.sendline("/quit")
            except Exception as e:
                LOG.warning(f"failed to send /quit: {e}")
            try:
                self.baresip.close()
            except Exception as e:
                LOG.warning(f"failed to close baresip process: {e}")
            try:
                self.baresip.kill(signal.SIGKILL)
            except Exception as e:
                LOG.debug(f"baresip process already dead: {e}")
        self.baresip = None

    def startBareSIPSubProcess(self) -> None:
        LOG.info("Starting BareSip process")
        self.baresip = pexpect.spawn(
            _find_baresip_binary() + ' -f ' + self.config_path)

    def send_dtmf(self, number: Union[str, int],
                  mode: str = "audio") -> None:
        """Send DTMF digits into the active call.

        :param mode: "audio" synthesizes in-band DTMF tones and streams
            them as call audio (audible, but not decoded as DTMF events by
            SIP peers). "keys" presses the digit keys on the baresip
            console, which sends real RTP telephone-events (RFC 4733) the
            peer reports as DTMF.
        """
        number = str(number)
        for n in number:
            if n not in "0123456789*#":
                LOG.error("invalid dtmf tone")
                return
        if mode == "keys":
            if not self.call_established:
                LOG.error("Can't send DTMF without an active call!")
                return
            LOG.info("Sending dtmf telephone-events for " + number)
            for n in number:
                self.baresip.sendline(n)
                sleep(0.3)
            return
        LOG.info("Sending dtmf tones for " + number)
        dtmf = join(tempfile.gettempdir(), number + ".wav")
        ToneGenerator().dtmf_to_wave(number, dtmf)
        self.send_audio(dtmf)

    def speak(self, speech: str, blocking: bool = True) -> None:
        if not self.call_established:
            LOG.error("Speaking without an active call!")
            return
        self.tts = self.tts or get_default_tts()
        if self.tts is None:
            raise RuntimeError(
                "no TTS configured - pass tts= or install baresipy[ovos]")
        # dumb sentence split - no NLP, just enough to allow barge-in
        # between sentences
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", speech)
                     if s.strip()]
        if not sentences:
            return
        self._tx_interrupted = False
        for sentence in sentences:
            if self._tx_interrupted or not self.call_established:
                self.handle_audio_interrupted()
                return
            LOG.info("Sending TTS for " + sentence)
            wav_file = join(tempfile.gettempdir(), "pybaresip_speak.wav")
            wav_file, phonemes = self.tts.get_tts(sentence, wav_file)
            self.send_audio(wav_file, block=blocking)
            if self._tx_interrupted or not self.call_established:
                self.handle_audio_interrupted()
                return
        sleep(0.5)

    def handle_audio_interrupted(self) -> None:
        LOG.debug("Audio playback interrupted")

    def stop_audio(self) -> None:
        """Immediately revert the audio source, interrupting any in-flight
        `send_audio`/`speak` playback (barge-in)."""
        LOG.info("Stopping audio playback")
        self._tx_interrupted = True
        self.do_command("/ausrc " + self._default_ausrc)

    def send_audio(self, wav_file: str, block: bool = True) -> float:
        if not self.call_established:
            LOG.error("Can't send audio without an active call!")
            return 0.0
        self._tx_interrupted = False
        wav_file, duration = self.convert_audio(
            wav_file, frame_rate=self.audio_frame_rate,
            channels=self.audio_channels)
        # send audio stream
        LOG.info("transmitting audio")
        self.do_command("/ausrc aufile," + wav_file)
        if block:
            # wait till playback ends, in small steps so a barge-in
            # (stop_audio) or call drop can cut this short
            deadline = _time() + max(duration - 0.5, 0)
            while _time() < deadline:
                if self._tx_interrupted or not self.call_established:
                    break
                sleep(0.1)
            if not self._tx_interrupted and self.call_established:
                # avoid baresip exiting
                self.do_command("/ausrc " + self._default_ausrc)
        else:
            timer = threading.Timer(duration, self._revert_audio_source)
            timer.daemon = True
            timer.start()
        return duration

    def _revert_audio_source(self) -> None:
        if not self._tx_interrupted:
            self.do_command("/ausrc " + self._default_ausrc)

    @staticmethod
    def convert_audio(input_file: str, outfile: Optional[str] = None,
                       frame_rate: int = 48000, channels: int = 2,
                       min_duration_s: float = 3.0) -> Tuple[str, float]:
        input_file = expanduser(input_file)
        sound = AudioSegment.from_file(input_file)
        sound += AudioSegment.silent(duration=500)
        # ensure minimum time
        # workaround baresip bug
        while sound.duration_seconds < min_duration_s:
            sound += AudioSegment.silent(duration=500)

        outfile = outfile or join(tempfile.gettempdir(), "pybaresip.wav")
        sound = sound.set_frame_rate(frame_rate)
        sound = sound.set_channels(channels)
        sound.export(outfile, format="wav")
        return outfile, sound.duration_seconds

    # this is played out loud over speakers
    def say(self, speech: str) -> None:
        if not self.call_established:
            LOG.warning("Speaking without an active call!")
        self.tts = self.tts or get_default_tts()
        if self.tts is None:
            raise RuntimeError(
                "no TTS configured - pass tts= or install baresipy[ovos]")
        wav_file = join(tempfile.gettempdir(), "pybaresip_say.wav")
        wav_file, phonemes = self.tts.get_tts(speech, wav_file)
        self.audio = self._play_wav(wav_file, blocking=True)

    def play(self, audio_file: str, blocking: bool = True) -> None:
        if not audio_file.endswith(".wav"):
            audio_file, duration = self.convert_audio(
                audio_file, frame_rate=self.audio_frame_rate,
                channels=self.audio_channels)
        self.audio = self._play_wav(audio_file, blocking=blocking)

    def stop_playing(self) -> None:
        if self.audio is not None:
            self.audio.kill()

    @staticmethod
    def _play_wav(wav_file: str, play_cmd: str = "aplay %1",
                   blocking: bool = False):
        play_mp3_cmd = str(play_cmd).split(" ")
        for index, cmd in enumerate(play_mp3_cmd):
            if cmd == "%1":
                play_mp3_cmd[index] = wav_file
        if blocking:
            return subprocess.call(play_mp3_cmd)
        else:
            return subprocess.Popen(play_mp3_cmd)

    # events
    def handle_incoming_call(self, number: str) -> None:
        LOG.info("Incoming call: " + number)
        if self.call_established:
            LOG.info("already in a call, rejecting")
            sleep(0.1)
            self.do_command("b")
        else:
            LOG.info("default behaviour, rejecting call")
            sleep(0.1)
            self.do_command("b")

    def handle_call_rejected(self, number: str) -> None:
        LOG.info("Rejected incoming call: " + number)

    def handle_call_timestamp(self, timestr: str) -> None:
        LOG.info("Call time: " + timestr)

    def handle_call_status(self, status: str) -> None:
        if status != self._call_status:
            LOG.debug("Call Status: " + status)

    def handle_call_start(self) -> None:
        number = self.current_call
        LOG.info("Calling: " + number)

    def handle_call_ringing(self) -> None:
        number = self.current_call
        LOG.info(number + " is Ringing")

    def handle_call_established(self) -> None:
        LOG.info("Call established")

    def handle_call_ended(self, reason: str, number: Optional[str] = None) -> None:
        LOG.info("Call ended")
        LOG.debug(f"Number: {number} , Reason: {reason}")

    def _handle_no_accounts(self) -> None:
        LOG.debug("No accounts setup")
        self.login()

    def handle_login_success(self) -> None:
        LOG.info("Logged in!")

    def handle_login_failure(self) -> None:
        LOG.error("Log in failed!")
        self.quit()

    def handle_login_retry(self, attempt: int) -> None:
        LOG.info(f"Retrying registration (attempt {attempt}/"
                  f"{self.max_login_retries})")

    def _schedule_login_retry(self) -> None:
        self._login_retry_count += 1
        if self._login_retry_count > self.max_login_retries:
            self.handle_login_failure()
            return
        self.handle_login_retry(self._login_retry_count)
        timer = threading.Timer(self.login_retry_delay, self.login)
        timer.daemon = True
        timer.start()

    def handle_ready(self) -> None:
        LOG.info("Ready for instructions")

    def handle_mic_muted(self) -> None:
        LOG.info("Microphone muted")

    def handle_mic_unmuted(self) -> None:
        LOG.info("Microphone unmuted")

    def handle_audio_stream_failure(self) -> None:
        LOG.debug("Aborting call, maybe we reached voicemail?")
        self.hang()

    def handle_dtmf_received(self, char: str, duration: int) -> None:
        LOG.info("Received DTMF symbol '{0}' duration={1}".format(char, duration))
        if self.current_call_info is not None:
            self.current_call_info.dtmf += char

    def _finalize_call_info(self, reason: Optional[str] = None) -> None:
        if self.current_call_info is None:
            return
        self.current_call_info.ended = _time()
        self.current_call_info.reason = reason
        self.call_history.append(self.current_call_info)
        if len(self.call_history) > 100:
            self.call_history.pop(0)
        self.current_call_info = None

    def handle_error(self, error: str) -> None:
        LOG.error(error)
        if error == "failed to set audio-source (No such device)":
            self.handle_audio_stream_failure()

    def handle_audio_source_error(self, error: str) -> None:
        """Called whenever baresip reports it could not set an
        audio-source, eg "(No such device)", "(Function not
        implemented)", "(No such file or directory)", etc - baresip
        appends whatever errno text applies. Override this to react to
        or recover from audio-source failures.

        Note this does not, by itself, hang up the call - the one
        special case that does (the exact "(No such device)" variant)
        is handled separately via `handle_error`/
        `handle_audio_stream_failure`, preserving prior behaviour.
        """
        LOG.warning("audio-source failure: " + error)

    def handle_unhandled_output(self, output: str) -> None:
        LOG.info("Received unhandled output: '{0}'".format(output))

    # line parsing
    def _handle_output_line(self, out: str) -> None:
        if "baresip is ready." in out:
            self.handle_ready()
            if not self._login:
                # registrar-less mode: ensure a local UA exists, no
                # registration to wait for
                self.login()
                self.ready = True
        elif "account: No SIP accounts found" in out:
            self._handle_no_accounts()
        elif "200 OK" in out:
            # baresip prints "All 1 useragent registered successfully!" only on
            # the FIRST successful registration. Every later one - after a
            # network drop, or the periodic re-REGISTER - reports success as a
            # bare 200 OK, so keying on the friendlier line leaves the phone
            # looking permanently disconnected after its first reconnect.
            self.ready = True
            self._login_retry_count = 0
            self.handle_login_success()
        elif "ua: SIP register failed:" in out or \
                "401 Unauthorized" in out or \
                "Register: Destination address required" in out or \
                "Register: Connection timed out" in out:
            self.handle_error(out)
            if self.max_login_retries > 0:
                self._schedule_login_retry()
            else:
                self.handle_login_failure()
        elif "Incoming call from: " in out:
            num = out.split("Incoming call from: ")[
                1].split(" - (press 'a' to accept)")[0].strip()
            self.current_call = num
            self._call_status = "INCOMING"
            user, host = parse_sip_uri(num)
            self.current_call_info = CallInfo(
                uri=num, user=user, host=host, direction="in",
                started=_time())
            self.handle_incoming_call(num)
        elif "call: rejecting incoming call from " in out:
            num = out.split("rejecting incoming call from ")[1].split(" ")[0].strip()
            self.handle_call_rejected(num)
        elif "call: SIP Progress: 180 Ringing" in out:
            self.handle_call_ringing()
            status = "RINGING"
            self.handle_call_status(status)
            self._call_status = status
        elif "call: connecting to " in out:
            n = out.split("call: connecting to '")[1].split("'")[0]
            self.current_call = n
            user, host = parse_sip_uri(n)
            self.current_call_info = CallInfo(
                uri=n, user=user, host=host, direction="out",
                started=_time())
            self.handle_call_start()
            status = "OUTGOING"
            self.handle_call_status(status)
            self._call_status = status
        elif "Call established:" in out:
            status = "ESTABLISHED"
            self.handle_call_status(status)
            self._call_status = status
            sleep(0.5)
            self.handle_call_established()
        elif "call: hold " in out:
            n = out.split("call: hold ")[1]
            status = "ON HOLD"
            self.handle_call_status(status)
            self._call_status = status
        elif "Call with " in out and \
                "terminated (duration: " in out:
            status = "DISCONNECTED"
            duration = out.split("terminated (duration: ")[1][:-1]
            self.handle_call_status(status)
            self._call_status = status
            self.handle_call_timestamp(duration)
            self.mic_muted = False
            self._finalize_call_info(reason=duration)
        elif "call muted" in out:
            self.mic_muted = True
            self.handle_mic_muted()
        elif "call un-muted" in out:
            self.mic_muted = False
            self.handle_mic_unmuted()
        elif "session closed:" in out:
            reason = out.split("session closed:")[1].strip()
            number = out.split(": session closed:")[0].strip()
            status = "DISCONNECTED"
            self.handle_call_status(status)
            self._call_status = status
            self.handle_call_ended(reason, number)
            self.mic_muted = False
            self._finalize_call_info(reason=reason)
        elif "(no active calls)" in out:
            status = "DISCONNECTED"
            self.handle_call_status(status)
            self._call_status = status
        elif "===== Call debug " in out:
            status = out.split("(")[1].split(")")[0]
            self.handle_call_status(status)
            self._call_status = status
        elif "--- List of active calls (1): ---" in \
                self._prev_output:
            if "ESTABLISHED" in out and self.current_call in out:
                ts = out.split("ESTABLISHED")[0].split(
                    "[line 1]")[1].strip()
                if ts != self._ts:
                    self._ts = ts
                    self.handle_call_timestamp(ts)
        elif "failed to set audio-source (" in out:
            # the error reason is interpolated by baresip (errno text),
            # eg "(No such device)" / "(Function not implemented)" /
            # "(No such file or directory)". handle_error preserves the
            # existing "(No such device)" -> hangup special case;
            # handle_audio_source_error is the new overridable hook that
            # every variant reaches, without adding any new hangups.
            error = out[out.index("failed to set audio-source ("):]
            self.handle_error(error)
            self.handle_audio_source_error(error)
        elif "terminated by signal" in out or "ua: stop all" in \
                out:
            self.running = False
        elif "transfer" in out.lower():
            # baresip (modules/menu/menu.c) has no dedicated "transfer
            # succeeded" line - success is only implied by the transferee
            # call reaching ESTABLISHED - so match generously here:
            #   "menu: transferring call <id> to '<uri>'" -> initiation
            #       accepted, treated as ok
            #   anything else containing "transfer" + fail/error -> failed
            lowered = out.lower()
            if "fail" in lowered or "error" in lowered:
                reason = out.strip()
                self.handle_transfer_failed(reason)
            elif "transferring call" in lowered:
                self.handle_transfer_ok()
            else:
                self.handle_unhandled_output(out)
        elif "DTMF" in out:
            # baresip logs DTMF differently per transport:
            #   legacy:   received DTMF: '1' (duration=250)
            #   SIP INFO: call: received SIP INFO DTMF: '1' (duration=250)
            #   in-band:  received in-band DTMF event: '1' (end=1)
            match = re.search(
                r"received (?:SIP INFO )?DTMF: '(.)' \(duration=(\d+)\)", out)
            if match:
                self.handle_dtmf_received(match.group(1), int(match.group(2)))
            else:
                match = re.search(
                    r"received in-band DTMF event: '(.)' \(end=(\d)\)", out)
                # only report the event end, to avoid duplicates
                if match and match.group(2) == "1":
                    self.handle_dtmf_received(match.group(1), 0)
                elif not match:
                    self.handle_unhandled_output(out)
        else:
            self.handle_unhandled_output(out)

    # event loop
    def run(self) -> None:
        self.running = True
        while self.running:
            try:
                # A baresip that died takes the phone with it unless something
                # puts it back. killBareSIPSubProcess() clears self.baresip,
                # which is the signal to spawn a replacement on the next pass.
                if self.baresip is None:
                    self.startBareSIPSubProcess()
                    continue
                if not self.baresip.isalive():
                    self.killBareSIPSubProcess()
                    sleep(0.5)
                    continue

                out = self.baresip.readline().decode("utf-8")

                if out != self._prev_output:
                    out = out.strip()
                    if self.debug:
                        LOG.debug(out)
                    if out:
                        try:
                            self._handle_output_line(out)
                        except Exception as e:
                            LOG.exception(f"error handling baresip output "
                                           f"line: {out!r} - {e}")
                    self._prev_output = out
            except pexpect.exceptions.EOF:
                # baresip exited
                self.running = False
            except OSError:
                # pty file descriptor closed under us (quit() racing the
                # readline loop)
                self.running = False
            except pexpect.exceptions.TIMEOUT:
                # nothing happened for a while
                pass
            except KeyboardInterrupt:
                self.running = False
            except Exception as e:
                # Anything not handled above. Stop rather than spin: this loop
                # is the phone, and a tight loop on a repeating error is worse
                # than a clean exit that systemd restarts.
                LOG.exception(f"unhandled error in baresip loop: {e}")
                self.running = False

        self.quit()

    def wait_until_ready(self) -> None:
        while not self.ready:
            sleep(0.1)
            if self.abort:
                return

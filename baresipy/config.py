from os.path import isdir
from typing import Optional
import re

from baresipy.utils.log import LOG

DEFAULT = """#
# baresip configuration
#

#------------------------------------------------------------------------------

# Core
poll_method		epoll		# poll, select, epoll ..

# SIP
sip_trans_bsize		128
#sip_listen		0.0.0.0:5060
#sip_certificate	cert.pem

# Call
call_local_timeout	120
call_max_calls		4

# Audio
#audio_path		/usr/share/baresip
audio_player		alsa,default
audio_source		alsa,default
audio_alert		alsa,default
#ausrc_srate		48000
#auplay_srate		48000
#ausrc_channels		0
#auplay_channels	0
#audio_txmode		poll		# poll, thread
audio_level		no
ausrc_format		s16		# s16, float, ..
auplay_format		s16		# s16, float, ..
auenc_format		s16		# s16, float, ..
audec_format		s16		# s16, float, ..

# Video
#video_source		v4l2,/dev/video0
#video_display		x11,nil
video_size		352x288
video_bitrate		500000
video_fps		25.00
video_fullscreen	yes
videnc_format		yuv420p

# AVT - Audio/Video Transport
rtp_tos			184
#rtp_ports		10000-20000
#rtp_bandwidth		512-1024 # [kbit/s]
rtcp_mux		no
jitter_buffer_delay	5-10		# frames
rtp_stats		no
#rtp_timeout		60

# Network
#dns_server		10.0.0.1:53
#net_interface		wlp0s20f3

# BFCP
#bfcp_proto		udp

#------------------------------------------------------------------------------
# Modules

module_path		/usr/lib/baresip/modules

# UI Modules
module			stdio.so
#module			cons.so
#module			evdev.so
#module			httpd.so

# Audio codec Modules (in order)
module			opus.so
#module			amr.so
#module			g7221.so
#module			g722.so
#module			g726.so
module			g711.so
#module			gsm.so
#module			l16.so
#module			bv32.so
#module			mpa.so
#module			codec2.so
#module			ilbc.so
#module			isac.so

# Audio filter Modules (in encoding order)
module			vumeter.so
#module			sndfile.so
#module			speex_aec.so
#module			speex_pp.so
#module			plc.so

# Audio driver Modules
module			alsa.so
module			pulse.so
#module			jack.so
#module			portaudio.so
#module			aubridge.so
module			aufile.so

# Video codec Modules (in order)
module			avcodec.so
#module			vp8.so
#module			vp9.so
#module			h265.so

# Video filter Modules (in encoding order)
#module			selfview.so
#module			snapshot.so
#module			swscale.so
#module			vidinfo.so

# Video source modules
#module			v4l.so
#module			v4l2.so
#module			v4l2_codec.so
#module			avformat.so
#module			x11grab.so
#module			cairo.so
#module			vidbridge.so

# Video display modules
#module			directfb.so
#module			x11.so
#module			sdl2.so
#module			fakevideo.so

# Audio/Video source modules
#module			rst.so
#module			gst1.so
#module			gst_video1.so

# Media NAT modules
module			stun.so
module			turn.so
module			ice.so
#module			natpmp.so
#module			pcp.so

# Media encryption modules
#module			srtp.so
#module			dtls_srtp.so
#module			zrtp.so


#------------------------------------------------------------------------------
# Temporary Modules (loaded then unloaded)

module_tmp		uuid.so
module_tmp		account.so


#------------------------------------------------------------------------------
# Application Modules

module_app		auloop.so
#module_app		b2bua.so
module_app		contact.so
module_app		debug_cmd.so
#module_app		dtmfio.so
#module_app		echo.so
#module_app		gtk.so
module_app		menu.so
#module_app		mwi.so
#module_app		natbd.so
#module_app		presence.so
#module_app		syslog.so
#module_app		mqtt.so
#module_app		ctrl_tcp.so
module_app		vidloop.so


#------------------------------------------------------------------------------
# Module parameters


cons_listen		0.0.0.0:5555

http_listen		0.0.0.0:8000

ctrl_tcp_listen		0.0.0.0:4444

evdev_device		/dev/input/event0

# Opus codec parameters
opus_bitrate		28000 # 6000-510000
#opus_stereo		yes
#opus_sprop_stereo	yes
#opus_cbr		no
#opus_inband_fec	no
#opus_dtx		no
#opus_mirror		no
#opus_complexity		10
#opus_application		audio	# {voip,audio}

vumeter_stderr		yes

# Selfview
video_selfview		window # {window,pip}
#selfview_size		64x64

# ICE
ice_turn		no
ice_debug		no
ice_nomination		regular	# {regular,aggressive}
ice_mode		full	# {full,lite}

# ZRTP
#zrtp_hash		no  # Disable SDP zrtp-hash (not recommended)

# Menu
#menu_bell		yes
#redial_attempts	3 # Num or <inf>
#redial_delay		5 # Delay in seconds
#ringback_disabled	yes
#statmode_default	off"""


def ensure_sndfile_recording(config: str, snd_path: str) -> str:
    """Ensure `module sndfile.so` is active and `snd_path` is set in a
    rendered (or user-provided) baresip config text blob.

    Works whether `config` came from `render_config` or was loaded from an
    existing config file, by patching the text directly.

    :param config: baresip config file contents
    :param snd_path: directory where call recordings should be written
    """
    # whitespace-tolerant match: some user-provided configs use spaces
    # instead of tabs between "module" and the module name, so do not
    # rely on the exact tab-formatted DEFAULT template bytes.
    sndfile_line = re.compile(
        r"^([ \t]*)(#[ \t]*)?module([ \t]+)sndfile\.so[ \t]*$",
        re.MULTILINE)
    module_line = re.compile(
        r"^([ \t]*)#?module([ \t]+)\S+\.so[ \t]*$", re.MULTILINE)

    match = sndfile_line.search(config)
    if match:
        # module line already present, commented or not - make sure it is
        # active, preserving the original indentation/spacing style
        leading, _comment, sep = match.group(1), match.group(2), \
            match.group(3)
        config = config[:match.start()] + \
            leading + "module" + sep + "sndfile.so" + config[match.end():]
    else:
        # no sndfile.so line at all - insert one after the last known
        # "module ..." line so it lands in the modules section
        last_module = None
        for m in module_line.finditer(config):
            last_module = m
        if last_module is not None:
            # reuse the same separator style (tabs vs spaces) as the
            # anchor line so the inserted line matches the surrounding
            # config's formatting
            sep = last_module.group(2)
            config = config[:last_module.end()] + \
                "\nmodule" + sep + "sndfile.so" + config[last_module.end():]
        else:
            # config has no recognizable modules section at all - this is
            # unexpected for a real baresip config, but still try to make
            # recording work rather than failing silently
            config = config.rstrip("\n") + \
                "\n\n# added by baresipy to enable call recording\n" \
                "module\t\tsndfile.so\n"
            LOG.warning(
                "baresip config has no 'module ...' lines - added a "
                "standalone sndfile.so module line, but this config may "
                "be malformed and rx recording might not work")

    final_match = sndfile_line.search(config)
    if final_match is None or final_match.group(0).lstrip().startswith("#"):
        LOG.warning(
            "failed to enable the sndfile.so module in the baresip "
            "config - call recording (record_rx) will not work")

    if "snd_path" in config:
        config = re.sub(r"^snd_path\s+.*$", "snd_path\t\t" + snd_path,
                         config, flags=re.MULTILINE)
    else:
        config += "\nsnd_path\t\t" + snd_path + "\n"

    return config


def render_config(audio_driver: str = "alsa,default",
                   headless: bool = False,
                   audio_path: Optional[str] = None,
                   enable_sndfile: bool = False,
                   snd_path: Optional[str] = None,
                   sip_cafile: Optional[str] = None,
                   enable_srtp: bool = False) -> str:
    """Render a baresip config file from the DEFAULT template.

    :param audio_driver: value passed to `audio_source`/`audio_player`/
        `audio_alert` when not headless, eg "alsa,default" or "pulse,default"
    :param headless: if True, do not load any real sound hardware modules
        (alsa.so/pulse.so). Instead use `ausine.so` as the audio source and
        `aufile.so` for playback, so baresip can run without any sound card
        present (see github issues #16/#17)
    :param audio_path: if a directory, patch `audio_path` to point at it; if
        False-y but not None, disable sound file loading entirely
    :param enable_sndfile: if True, activate the `sndfile.so` module so
        baresip records call audio (rx/tx wav files) into `snd_path`
    :param snd_path: directory to write call recordings into, required if
        `enable_sndfile` is True
    :param sip_cafile: if set, points `sip_cafile` at this path, so baresip
        can verify the server certificate when `transport="tls"` is used
    :param enable_srtp: if True, load the `srtp.so` module so SRTP media
        encryption is available (see `media_encryption` on `BareSIP`)
    """
    config = DEFAULT

    if headless:
        config = config.replace(
            "audio_player		alsa,default",
            "audio_player		aufile,/dev/null")
        config = config.replace(
            "audio_source		alsa,default",
            "audio_source		ausine,400")
        config = config.replace(
            "audio_alert		alsa,default",
            "audio_alert		aufile,/dev/null")
        config = config.replace(
            "module			alsa.so\nmodule			pulse.so",
            "#module			alsa.so\n#module			pulse.so")
        if "module			ausine.so" not in config:
            config = config.replace(
                "module			aufile.so\n",
                "module			aufile.so\nmodule			ausine.so\n", 1)
    else:
        config = config.replace("audio_player		alsa,default",
                                 "audio_player		" + audio_driver)
        config = config.replace("audio_source		alsa,default",
                                 "audio_source		" + audio_driver)
        config = config.replace("audio_alert		alsa,default",
                                 "audio_alert		" + audio_driver)

    if audio_path is not None and "#audio_path" in config:
        if audio_path is False:
            # sounds disabled
            config = config.replace(
                "#audio_path		/usr/share/baresip",
                "audio_path		/dont/load")
        elif audio_path and isdir(audio_path):
            config = config.replace(
                "#audio_path		/usr/share/baresip",
                "audio_path		" + audio_path)

    if enable_sndfile:
        if not snd_path:
            raise ValueError("snd_path is required when enable_sndfile=True")
        config = ensure_sndfile_recording(config, snd_path)

    if sip_cafile:
        if "#sip_certificate	cert.pem" in config:
            config = config.replace(
                "#sip_certificate	cert.pem",
                "#sip_certificate	cert.pem\nsip_cafile\t\t" + sip_cafile)
        else:
            config += "\nsip_cafile\t\t" + sip_cafile + "\n"

    if enable_srtp:
        config = config.replace(
            "#module			srtp.so", "module			srtp.so")

    return config

#!/usr/bin/env python
# coding=utf-8

# aeneas is a Python/C library and a set of tools
# to automagically synchronize audio and text (aka forced alignment)
#
# Copyright (C) 2012-2013, Alberto Pettarin (www.albertopettarin.it)
# Copyright (C) 2013-2015, ReadBeyond Srl   (www.readbeyond.it)
# Copyright (C) 2015-2017, Alberto Pettarin (www.albertopettarin.it)
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""
This module contains the following classes:

* :class:`~aeneas.audiofile.AudioFile`, representing an audio file;
* :class:`~aeneas.audiofile.AudioFileConverterError`,
* :class:`~aeneas.audiofile.AudioFileNotInitializedError`,
* :class:`~aeneas.audiofile.AudioFileProbeError`, and
* :class:`~aeneas.audiofile.AudioFileUnsupportedFormatError`,
  representing errors generated by audio files.
"""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
import numpy

from aeneas.exacttiming import TimeValue
from aeneas.ffmpegwrapper import FFMPEGPathError
from aeneas.ffmpegwrapper import FFMPEGWrapper
from aeneas.ffprobewrapper import FFPROBEParsingError
from aeneas.ffprobewrapper import FFPROBEPathError
from aeneas.ffprobewrapper import FFPROBEUnsupportedFormatError
from aeneas.ffprobewrapper import FFPROBEWrapper
from aeneas.logger import Loggable
from aeneas.runtimeconfiguration import RuntimeConfiguration
from aeneas.wavfile import read as scipywavread
from aeneas.wavfile import write as scipywavwrite
import aeneas.globalfunctions as gf


class AudioFileConverterError(Exception):
    """
    Error raised when the audio converter executable cannot be executed.
    """
    pass


class AudioFileNotInitializedError(Exception):
    """
    Error raised when trying to access audio samples from
    an :class:`~aeneas.audiofile.AudioFile` object which
    has not been initialized yet.
    """
    pass


class AudioFileProbeError(Exception):
    """
    Error raised when the audio probe executable cannot be executed.
    """
    pass


class AudioFileUnsupportedFormatError(Exception):
    """
    Error raised when the format of the given file cannot be decoded.
    """
    pass


class AudioFile(Loggable):
    """
    A class representing an audio file.

    This class can be used either to extract properties
    from an audio file on disk,
    or to load/edit/save a monoaural (single channel) audio file,
    represented as an array of audio samples.

    The properties of the audio file (length, format, etc.)
    can set by invoking the :func:`~aeneas.audiofile.AudioFile.read_properties` function,
    which calls an audio file probe.
    (Currently, the probe is :class:`~aeneas.ffprobewrapper.FFPROBEWrapper`)

    Moreover, this class can read the audio data,
    by converting the original file format
    into a temporary PCM16 Mono WAVE (RIFF) file,
    which is deleted as soon as audio data is read in memory.
    (Currently, the converter is :class:`~aeneas.ffmpegwrapper.FFMPEGWrapper`)

    The internal representation of the wave is a
    a NumPy 1D array of ``float64`` values in ``[-1.0, 1.0]``.
    It supports append, reverse, and trim operations.
    Audio samples can be written to file.
    Memory can be pre-allocated to speed append operations up.
    Allocated memory is doubled when an append operation
    requires more memory than what is available;
    this leads to an amortized linear complexity
    (in the number of audio samples)
    for append operations.

    .. note:: Support for stereo WAVE files might be implemented in a future version

    :param string file_path: the path of the audio file
    :param tuple file_format: the format of the audio file, if known in advance: ``(codec, channels, rate)`` or ``None``
    :param rconf: a runtime configuration
    :type  rconf: :class:`~aeneas.runtimeconfiguration.RuntimeConfiguration`
    :param logger: the logger object
    :type  logger: :class:`~aeneas.logger.Logger`
    """

    FILE_EXTENSIONS = [
        u"3g2",
        u"3gp",
        u"aa",
        u"aa3",
        u"aac",
        u"aax",
        u"aiff",
        u"alac",
        u"amr",
        u"ape",
        u"asf",
        u"at3",
        u"at9",
        u"au",
        u"avi",
        u"awb",
        u"celt",
        u"dct",
        u"dss",
        u"dvf",
        u"eac",
        u"flac",
        u"flv",
        u"gsm",
        u"m4a",
        u"m4b",
        u"m4p",
        u"m4v",
        u"mid",
        u"midi",
        u"mkv",
        u"mmf",
        u"mov",
        u"mp2",
        u"mp3",
        u"mp4",
        u"mpc",
        u"mpeg",
        u"mpg",
        u"mpv",
        u"msv",
        u"oga",
        u"ogg",
        u"ogv",
        u"oma",
        u"opus",
        u"pcm",
        u"qt",
        u"ra",
        u"ram",
        u"raw",
        u"riff",
        u"rm",
        u"rmvb",
        u"shn",
        u"sln",
        u"theora",
        u"tta",
        u"vob",
        u"vorbis",
        u"vox",
        u"wav",
        u"webm",
        u"wma",
        u"wmv",
        u"wv",
        u"yuv",
    ]
    """ Extensions of common formats for audio (and video) files. """

    TAG = u"AudioFile"

    def __init__(self, file_path=None, file_format=None, rconf=None, logger=None):
        super(AudioFile, self).__init__(rconf=rconf, logger=logger)
        self.file_path = file_path
        self.file_format = file_format
        self.file_size = None
        self.audio_length = None
        self.audio_format = None
        self.audio_sample_rate = None
        self.audio_channels = None
        self.__samples_capacity = 0
        self.__samples_length = 0
        self.__samples = None

    def __unicode__(self):
        msg = [
            u"File path:         %s" % self.file_path,
            u"File format:       %s" % self.file_format,
            u"File size (bytes): %s" % gf.safe_int(self.file_size),
            u"Audio length (s):  %s" % gf.safe_float(self.audio_length),
            u"Audio format:      %s" % self.audio_format,
            u"Audio sample rate: %s" % gf.safe_int(self.audio_sample_rate),
            u"Audio channels:    %s" % gf.safe_int(self.audio_channels),
            u"Samples capacity:  %s" % gf.safe_int(self.__samples_capacity),
            u"Samples length:    %s" % gf.safe_int(self.__samples_length),
        ]
        return u"\n".join(msg)

    def __str__(self):
        return gf.safe_str(self.__unicode__())

    @property
    def file_path(self):
        """
        The path of the audio file.

        :rtype: string
        """
        return self.__file_path

    @file_path.setter
    def file_path(self, file_path):
        self.__file_path = file_path

    @property
    def file_size(self):
        """
        The size of the audio file, in bytes.

        :rtype: int
        """
        return self.__file_size

    @file_size.setter
    def file_size(self, file_size):
        self.__file_size = file_size

    @property
    def audio_length(self):
        """
        The length of the audio file, in seconds.

        :rtype: :class:`~aeneas.exacttiming.TimeValue`
        """
        return self.__audio_length

    @audio_length.setter
    def audio_length(self, audio_length):
        self.__audio_length = audio_length

    @property
    def audio_format(self):
        """
        The format of the audio file.

        :rtype: string
        """
        return self.__audio_format

    @audio_format.setter
    def audio_format(self, audio_format):
        self.__audio_format = audio_format

    @property
    def audio_sample_rate(self):
        """
        The sample rate of the audio file, in samples per second.

        :rtype: int
        """
        return self.__audio_sample_rate

    @audio_sample_rate.setter
    def audio_sample_rate(self, audio_sample_rate):
        self.__audio_sample_rate = audio_sample_rate

    @property
    def audio_channels(self):
        """
        The number of channels of the audio file.

        :rtype: int
        """
        return self.__audio_channels

    @audio_channels.setter
    def audio_channels(self, audio_channels):
        self.__audio_channels = audio_channels

    @property
    def audio_samples(self):
        """
        The audio audio_samples, that is, an array of ``float64`` values,
        each representing an audio sample in ``[-1.0, 1.0]``.

        Note that this function returns a view into the
        first ``self.__samples_length`` elements of ``self.__samples``.
        If you want to clone the values,
        you must use e.g. ``numpy.array(audiofile.audio_samples)``.

        :rtype: :class:`numpy.ndarray` (1D, view)
        :raises: :class:`~aeneas.audiofile.AudioFileNotInitializedError`: if the audio file is not initialized yet
        """
        if self.__samples is None:
            if self.file_path is None:
                self.log_exc(u"AudioFile object not initialized", None, True, AudioFileNotInitializedError)
            else:
                self.read_samples_from_file()
        return self.__samples[0:self.__samples_length]

    def read_properties(self):
        """
        Populate this object by reading
        the audio properties of the file at the given path.

        Currently this function uses
        :class:`~aeneas.ffprobewrapper.FFPROBEWrapper`
        to get the audio file properties.

        :raises: :class:`~aeneas.audiofile.AudioFileProbeError`: if the path to the ``ffprobe`` executable cannot be called
        :raises: :class:`~aeneas.audiofile.AudioFileUnsupportedFormatError`: if the audio file has a format not supported
        :raises: OSError: if the audio file cannot be read
        """
        self.log(u"Reading properties...")

        # check the file can be read
        if not gf.file_can_be_read(self.file_path):
            self.log_exc(u"File '%s' cannot be read" % (self.file_path), None, True, OSError)

        # get the file size
        self.log([u"Getting file size for '%s'", self.file_path])
        self.file_size = gf.file_size(self.file_path)
        self.log([u"File size for '%s' is '%d'", self.file_path, self.file_size])

        # get the audio properties using FFPROBEWrapper
        try:
            self.log(u"Reading properties with FFPROBEWrapper...")
            properties = FFPROBEWrapper(
                rconf=self.rconf,
                logger=self.logger
            ).read_properties(self.file_path)
            self.log(u"Reading properties with FFPROBEWrapper... done")
        except FFPROBEPathError:
            self.log_exc(u"Unable to call ffprobe executable", None, True, AudioFileProbeError)
        except (FFPROBEUnsupportedFormatError, FFPROBEParsingError):
            self.log_exc(u"Audio file format not supported by ffprobe", None, True, AudioFileUnsupportedFormatError)

        # save relevant properties in results inside the audiofile object
        self.audio_length = TimeValue(properties[FFPROBEWrapper.STDOUT_DURATION])
        self.audio_format = properties[FFPROBEWrapper.STDOUT_CODEC_NAME]
        self.audio_sample_rate = gf.safe_int(properties[FFPROBEWrapper.STDOUT_SAMPLE_RATE])
        self.audio_channels = gf.safe_int(properties[FFPROBEWrapper.STDOUT_CHANNELS])
        self.log([u"Stored audio_length: '%s'", self.audio_length])
        self.log([u"Stored audio_format: '%s'", self.audio_format])
        self.log([u"Stored audio_sample_rate: '%s'", self.audio_sample_rate])
        self.log([u"Stored audio_channels: '%s'", self.audio_channels])
        self.log(u"Reading properties... done")

    def read_samples_from_file(self):
        """
        Load the audio samples from file into memory.

        If ``self.file_format`` is ``None`` or it is not
        ``("pcm_s16le", 1, self.rconf.sample_rate)``,
        the file will be first converted
        to a temporary PCM16 mono WAVE file.
        Audio data will be read from this temporary file,
        which will be then deleted from disk immediately.

        Otherwise,
        the audio data will be read directly
        from the given file,
        which will not be deleted from disk.

        :raises: :class:`~aeneas.audiofile.AudioFileConverterError`: if the path to the ``ffmpeg`` executable cannot be called
        :raises: :class:`~aeneas.audiofile.AudioFileUnsupportedFormatError`: if the audio file has a format not supported
        :raises: OSError: if the audio file cannot be read
        """
        self.log(u"Loading audio data...")

        # check the file can be read
        if not gf.file_can_be_read(self.file_path):
            self.log_exc(u"File '%s' cannot be read" % (self.file_path), None, True, OSError)

        # determine if we need to convert the audio file
        convert_audio_file = (
            (self.file_format is None) or
            (
                (self.rconf.safety_checks) and
                (self.file_format != ("pcm_s16le", 1, self.rconf.sample_rate))
            )
        )

        # convert the audio file if needed
        if convert_audio_file:
            # convert file to PCM16 mono WAVE with correct sample rate
            self.log(u"self.file_format is None or not good => converting self.file_path")
            tmp_handler, tmp_file_path = gf.tmp_file(suffix=u".wav", root=self.rconf[RuntimeConfiguration.TMP_PATH])
            self.log([u"Temporary PCM16 mono WAVE file: '%s'", tmp_file_path])
            try:
                self.log(u"Converting audio file to mono...")
                converter = FFMPEGWrapper(rconf=self.rconf, logger=self.logger)
                converter.convert(self.file_path, tmp_file_path)
                self.file_format = ("pcm_s16le", 1, self.rconf.sample_rate)
                self.log(u"Converting audio file to mono... done")
            except FFMPEGPathError:
                gf.delete_file(tmp_handler, tmp_file_path)
                self.log_exc(u"Unable to call ffmpeg executable", None, True, AudioFileConverterError)
            except OSError:
                gf.delete_file(tmp_handler, tmp_file_path)
                self.log_exc(u"Audio file format not supported by ffmpeg", None, True, AudioFileUnsupportedFormatError)
        else:
            # read the file directly
            if self.rconf.safety_checks:
                self.log(u"self.file_format is good => reading self.file_path directly")
            else:
                self.log_warn(u"Safety checks disabled => reading self.file_path directly")
            tmp_handler = None
            tmp_file_path = self.file_path

        # TODO allow calling C extension cwave to read samples faster
        try:
            self.audio_format = "pcm16"
            self.audio_channels = 1
            self.audio_sample_rate, self.__samples = scipywavread(tmp_file_path)
            # scipy reads a sample as an int16_t, that is, a number in [-32768, 32767]
            # so we convert it to a float64 in [-1, 1]
            self.__samples = self.__samples.astype("float64") / 32768
            self.__samples_capacity = len(self.__samples)
            self.__samples_length = self.__samples_capacity
            self._update_length()
        except ValueError:
            self.log_exc(u"Audio format not supported by scipywavread", None, True, AudioFileUnsupportedFormatError)

        # if we converted the audio file, delete the temporary converted audio file
        if convert_audio_file:
            gf.delete_file(tmp_handler, tmp_file_path)
            self.log([u"Deleted temporary audio file: '%s'", tmp_file_path])

        self._update_length()
        self.log([u"Sample length:  %.3f", self.audio_length])
        self.log([u"Sample rate:    %d", self.audio_sample_rate])
        self.log([u"Audio format:   %s", self.audio_format])
        self.log([u"Audio channels: %d", self.audio_channels])
        self.log(u"Loading audio data... done")

    def preallocate_memory(self, capacity):
        """
        Preallocate memory to store audio samples,
        to avoid repeated new allocations and copies
        while performing several consecutive append operations.

        If ``self.__samples`` is not initialized,
        it will become an array of ``capacity`` zeros.

        If ``capacity`` is larger than the current capacity,
        the current ``self.__samples`` will be extended with zeros.

        If ``capacity`` is smaller than the current capacity,
        the first ``capacity`` values of ``self.__samples``
        will be retained.

        :param int capacity: the new capacity, in number of samples
        :raises: ValueError: if ``capacity`` is negative

        .. versionadded:: 1.5.0
        """
        if capacity < 0:
            raise ValueError(u"The capacity value cannot be negative")
        if self.__samples is None:
            self.log(u"Not initialized")
            self.__samples = numpy.zeros(capacity)
            self.__samples_length = 0
        else:
            self.log([u"Previous sample length was   (samples): %d", self.__samples_length])
            self.log([u"Previous sample capacity was (samples): %d", self.__samples_capacity])
            self.__samples = numpy.resize(self.__samples, capacity)
            self.__samples_length = min(self.__samples_length, capacity)
        self.__samples_capacity = capacity
        self.log([u"Current sample capacity is   (samples): %d", self.__samples_capacity])

    def minimize_memory(self):
        """
        Reduce the allocated memory to the minimum
        required to store the current audio samples.

        This function is meant to be called
        when building a wave incrementally,
        after the last append operation.

        .. versionadded:: 1.5.0
        """
        if self.__samples is None:
            self.log(u"Not initialized, returning")
        else:
            self.log(u"Initialized, minimizing memory...")
            self.preallocate_memory(self.__samples_length)
            self.log(u"Initialized, minimizing memory... done")

    def add_samples(self, samples, reverse=False):
        """
        Concatenate the given new samples to the current audio data.

        This function initializes the memory if no audio data
        is present already.

        If ``reverse`` is ``True``, the new samples
        will be reversed and then concatenated.

        :param samples: the new samples to be concatenated
        :type  samples: :class:`numpy.ndarray` (1D)
        :param bool reverse: if ``True``, concatenate new samples after reversing them

        .. versionadded:: 1.2.1
        """
        self.log(u"Adding samples...")
        samples_length = len(samples)
        current_length = self.__samples_length
        future_length = current_length + samples_length
        if (self.__samples is None) or (self.__samples_capacity < future_length):
            self.preallocate_memory(2 * future_length)
        if reverse:
            self.__samples[current_length:future_length] = samples[::-1]
        else:
            self.__samples[current_length:future_length] = samples[:]
        self.__samples_length = future_length
        self._update_length()
        self.log(u"Adding samples... done")

    def reverse(self):
        """
        Reverse the audio data.

        :raises: :class:`~aeneas.audiofile.AudioFileNotInitializedError`: if the audio file is not initialized yet

        .. versionadded:: 1.2.0
        """
        if self.__samples is None:
            if self.file_path is None:
                self.log_exc(u"AudioFile object not initialized", None, True, AudioFileNotInitializedError)
            else:
                self.read_samples_from_file()
        self.log(u"Reversing...")
        self.__samples[0:self.__samples_length] = numpy.flipud(self.__samples[0:self.__samples_length])
        self.log(u"Reversing... done")

    def trim(self, begin=None, length=None):
        """
        Get a slice of the audio data of ``length`` seconds,
        starting from ``begin`` seconds.

        If audio data is not loaded, load it and then slice it.

        :param begin: the start position, in seconds
        :type  begin: :class:`~aeneas.exacttiming.TimeValue`
        :param length: the  position, in seconds
        :type  length: :class:`~aeneas.exacttiming.TimeValue`
        :raises: TypeError: if one of the arguments is not ``None``
                            or :class:`~aeneas.exacttiming.TimeValue`

        .. versionadded:: 1.2.0
        """
        for variable, name in [(begin, "begin"), (length, "length")]:
            if (variable is not None) and (not isinstance(variable, TimeValue)):
                raise TypeError(u"%s is not None or TimeValue" % name)
        self.log(u"Trimming...")
        if (begin is None) and (length is None):
            self.log(u"begin and length are both None: nothing to do")
        else:
            if begin is None:
                begin = TimeValue("0.000")
                self.log([u"begin was None, now set to %.3f", begin])
            begin = min(max(TimeValue("0.000"), begin), self.audio_length)
            self.log([u"begin is %.3f", begin])
            if length is None:
                length = self.audio_length - begin
                self.log([u"length was None, now set to %.3f", length])
            length = min(max(TimeValue("0.000"), length), self.audio_length - begin)
            self.log([u"length is %.3f", length])
            begin_index = int(begin * self.audio_sample_rate)
            end_index = int((begin + length) * self.audio_sample_rate)
            new_idx = end_index - begin_index
            self.__samples[0:new_idx] = self.__samples[begin_index:end_index]
            self.__samples_length = new_idx
            self._update_length()
        self.log(u"Trimming... done")

    def write(self, file_path):
        """
        Write the audio data to file.
        Return ``True`` on success, or ``False`` otherwise.

        :param string file_path: the path of the output file to be written
        :raises: :class:`~aeneas.audiofile.AudioFileNotInitializedError`: if the audio file is not initialized yet

        .. versionadded:: 1.2.0
        """
        if self.__samples is None:
            if self.file_path is None:
                self.log_exc(u"AudioFile object not initialized", None, True, AudioFileNotInitializedError)
            else:
                self.read_samples_from_file()
        self.log([u"Writing audio file '%s'...", file_path])
        try:
            # our value is a float64 in [-1, 1]
            # scipy writes the sample as an int16_t, that is, a number in [-32768, 32767]
            data = (self.audio_samples * 32768).astype("int16")
            scipywavwrite(file_path, self.audio_sample_rate, data)
        except Exception as exc:
            self.log_exc(u"Error writing audio file to '%s'" % (file_path), exc, True, OSError)
        self.log([u"Writing audio file '%s'... done", file_path])

    def clear_data(self):
        """
        Clear the audio data, freeing memory.
        """
        self.log(u"Clear audio_data")
        self.__samples_capacity = 0
        self.__samples_length = 0
        self.__samples = None

    def _update_length(self):
        """
        Update the audio length property,
        according to the length of the current audio data
        and audio sample rate.

        This function fails silently if one of the two is ``None``.
        """
        if (self.audio_sample_rate is not None) and (self.__samples is not None):
            self.audio_length = TimeValue(self.__samples_length) / TimeValue(self.audio_sample_rate)

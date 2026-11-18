"""Frames are prepared for the picture off the GUI thread: 4K is halved, HDR10 retagged."""

import numpy
from PySide6.QtCore import QSize
from PySide6.QtMultimedia import QVideoFrame, QVideoFrameFormat

from torrentlinker.gui.media import DisplayFrames

Format = QVideoFrameFormat


def frame(transfer, pixel=Format.PixelFormat.Format_P010, size=QSize(64, 32), peak=1e7):
    shape = Format(size, pixel)
    shape.setColorTransfer(transfer)
    shape.setColorSpace(Format.ColorSpace.ColorSpace_BT2020)
    shape.setMaxLuminance(peak)
    made = QVideoFrame(shape)
    assert made.map(QVideoFrame.MapMode.WriteOnly)
    for plane in range(made.planeCount()):
        bits = made.bits(plane)
        bits[:] = bytes((i * 7 + plane) % 251 for i in range(len(bits)))
    made.unmap()
    return made


def plane(video, index, rows, dtype):
    assert video.map(QVideoFrame.MapMode.ReadOnly)
    try:
        line = video.bytesPerLine(index) // numpy.dtype(dtype).itemsize
        bits = numpy.frombuffer(bytes(video.bits(index)), dtype)
        return bits[: rows * line].reshape(rows, line)
    finally:
        video.unmap()


def test_hdr10_frames_get_their_real_peak_and_a_matrix_qt_converts_in_range(qapp):
    original = frame(Format.ColorTransfer.ColorTransfer_ST2084)
    fixed = DisplayFrames.prepared(original)
    shape = fixed.surfaceFormat()
    assert shape.maxLuminance() == 1000
    assert shape.colorSpace() == Format.ColorSpace.ColorSpace_BT601
    assert shape.colorTransfer() == Format.ColorTransfer.ColorTransfer_ST2084
    assert fixed.size() == original.size()
    for index, rows in ((0, 32), (1, 16)):
        assert (
            plane(fixed, index, rows, numpy.uint16)[:, :64]
            == plane(original, index, rows, numpy.uint16)[:, :64]
        ).all()


def test_frames_much_larger_than_the_picture_are_halved_until_they_fit(qapp):
    original = frame(Format.ColorTransfer.ColorTransfer_ST2084)
    small = DisplayFrames.prepared(original, QSize(16, 8))
    assert small.size() == QSize(16, 8)  # 64x32 halved twice
    luma = plane(original, 0, 32, numpy.uint16)[:, :64]
    assert (plane(small, 0, 8, numpy.uint16)[:, :16] == luma[::4, ::4]).all()
    chroma = plane(original, 1, 16, numpy.uint16)[:, :64].reshape(16, 32, 2)
    assert (plane(small, 1, 4, numpy.uint16)[:, :16].reshape(4, 8, 2) == chroma[::4, ::4]).all()


def test_planar_8_bit_frames_are_halved_plane_by_plane(qapp):
    original = frame(
        Format.ColorTransfer.ColorTransfer_BT709, Format.PixelFormat.Format_YUV420P, peak=100
    )
    half = DisplayFrames.prepared(original, QSize(32, 16))
    assert half.size() == QSize(32, 16)
    assert half.surfaceFormat().colorSpace() == Format.ColorSpace.ColorSpace_BT2020
    for index, rows, columns in ((0, 32, 64), (1, 16, 32), (2, 16, 32)):
        source = plane(original, index, rows, numpy.uint8)[:, :columns]
        result = plane(half, index, rows // 2, numpy.uint8)[:, : columns // 2]
        assert (result == source[::2, ::2]).all()


def test_frames_that_fit_and_are_not_hdr10_pass_through_untouched(qapp):
    original = frame(Format.ColorTransfer.ColorTransfer_BT709, peak=100)
    assert DisplayFrames.prepared(original, QSize(64, 32)) is original
    assert DisplayFrames.prepared(original) is original

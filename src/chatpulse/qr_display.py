"""Render an ephemeral Telegram login token as a QR code in a local TTY.

Never display the raw login URI, persist QR images, or include a QR token
in a log or error message. Terminal scrollback may still contain the QR image.
"""
from __future__ import annotations

import sys


def show_qr(url: str) -> None:
    if not sys.stdout.isatty():
        raise RuntimeError("QR login requires a local interactive terminal")
    if not url.startswith("tg://login?token="):
        raise ValueError("Unexpected QR login URI")
    import qrcode

    code = qrcode.QRCode(border=3, box_size=1)
    code.add_data(url)
    code.make(fit=True)
    matrix = code.get_matrix()
    print("\nScan this code with Telegram on your phone:")
    print("Settings > Devices > Link Desktop Device (Scan QR)")
    # Two vertical modules per Unicode cell keep the QR compact.
    # Black foreground + white background give conventional QR polarity.
    for index in range(0, len(matrix), 2):
        upper = matrix[index]
        lower = matrix[index + 1] if index + 1 < len(matrix) else [False] * len(upper)
        line = "".join(
            "█" if top and bottom else
            "▀" if top else "▄" if bottom else " "
            for top, bottom in zip(upper, lower)
        )
        print("\x1b[30m\x1b[47m" + line + "\x1b[0m")
    print("Confirm on your phone. This token expires shortly; never share screenshots.")

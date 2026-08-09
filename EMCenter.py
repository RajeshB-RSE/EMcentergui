"""
EMCenter.py

Driver for the ETS-Lindgren EMCenter Modular RF Platform. Talks to any
number of EMControl (7006-001) Positioner Controller plug-in cards, in any
slot, over a single PyVISA connection.

Axes are addressed as (slot, device), e.g. (1, "A"), matching the EMControl
command prefix "sd" described in the 7006-001 User Manual (Part #399348
Rev. B). A single EMCenter chassis can host several axes across several
slots -- towers and turntables alike -- all reachable through one VISA
session.

Command reference: EMControl 7006-001 User Manual, Part #399348 Rev. B.

Basic usage:
    from EMCenter import EMCenter

    MAST1 = (1, "A")
    MAST2 = (1, "B")
    TURNTABLE = (2, "A")

    with EMCenter(resource="TCPIP0::192.168.0.110::inst0::INSTR") as em:
        em.seek(*MAST1, 150)
        em.wait_until_idle(*MAST1)
        print(em.position(*MAST1))          # 150.0

        # Move two axes at the same time, then wait for both
        em.seek_many([(*MAST1, 250), (*TURNTABLE, 250)])
        em.wait_all_idle([MAST1, TURNTABLE])

Author : Rajesh
"""

import time
import logging

import pyvisa


logger = logging.getLogger("EMCenter")


class EMCenterError(Exception):
    """Raised for EMCenter communication or device errors."""
    pass


# Device Dependent Error Register bit map (EMControl manual, ERR? command)
ERROR_MAP = {
    1: "Parameters Lost",
    2: "Motor Not Moving",
    3: "Motor Not Stopping",
    4: "Moving Wrong Direction",
    5: "Hard Limit Hit",
    6: "Polarization Limit Violation",
    7: "Communication Lost",
    8: "Flotation Violation",
    9: "Encoder Failure",
}


class EMCenter:
    """
    High level driver for one EMCenter chassis. Every axis (a tower or a
    turntable on an EMControl card) is identified by its (slot, device)
    pair and addressed independently -- there is no fixed "the tower" /
    "the turntable" on this class, so any mix of masts and turntables
    across any slots is supported.
    """

    def __init__(
        self,
        resource="TCPIP0::192.168.0.110::inst0::INSTR",
        timeout=5000,
        backend="@py",
    ):
        """
        backend: PyVISA backend to use. "@py" (default) uses the pure
        Python pyvisa-py backend, which requires no NI-VISA driver
        install -- important for a standalone double-click app. Pass
        "" (empty string) to use the system default VISA implementation
        (e.g. NI-VISA) instead, if you have that installed.
        """
        self.resource_name = resource
        self.timeout = timeout
        self.backend = backend

        self.rm = None
        self.inst = None

    # ------------------------------------------------------------
    # Context manager support
    # ------------------------------------------------------------

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()

    # ------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------

    def connect(self):
        self.rm = pyvisa.ResourceManager(self.backend)
        self.inst = self.rm.open_resource(self.resource_name)

        self.inst.timeout = self.timeout
        self.inst.read_termination = "\r"
        self.inst.write_termination = "\r"

        logger.info("Connected to EMCenter at %s", self.resource_name)

    def disconnect(self):
        if self.inst:
            try:
                self.inst.close()
            finally:
                self.inst = None
            logger.info("Disconnected from EMCenter")

        if self.rm:
            self.rm.close()
            self.rm = None

    def reconnect(self):
        logger.warning("Reconnecting to EMCenter...")
        self.disconnect()
        time.sleep(1)
        self.connect()

    def is_connected(self):
        return self.inst is not None

    # ------------------------------------------------------------
    # Low level I/O
    # ------------------------------------------------------------

    def _query(self, command, retries=2):
        """
        Send a command and return its response, retrying with a fresh
        VISA session if communication fails.
        """
        if not self.inst:
            raise EMCenterError("Not connected to EMCenter")

        last_exc = None

        for attempt in range(1, retries + 1):
            try:
                logger.debug(">> %s", command)
                response = self.inst.query(command).strip()
                logger.debug("<< %s", response)
                return response
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "Command '%s' failed (attempt %d/%d): %s",
                    command, attempt, retries, exc
                )
                self.reconnect()
                time.sleep(0.5)

        raise EMCenterError(f"Command '{command}' failed: {last_exc}")

    @staticmethod
    def _addr(slot, device, cmd):
        return f"{slot}{device}{cmd}"

    # ------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------

    @staticmethod
    def _parse_position(response):
        """
        Parse a CP? response and return the numeric value only.

        Tower response     : "XXX.XX CM"
        Turntable response : "XXX.XX DEGREES"
        """
        try:
            return float(response.split()[0])
        except (ValueError, IndexError):
            raise EMCenterError(f"Unexpected position response: '{response}'")

    @staticmethod
    def _is_ok(response):
        """True if the device acknowledged an action command with 'OK'."""
        return response.strip().upper() == "OK"

    # ------------------------------------------------------------
    # Motion -- single axis
    # ------------------------------------------------------------

    def seek(self, slot, device, position):
        """
        Move an axis to an absolute position (cm for towers, degrees for
        turntables), by the shortest path. Non-blocking -- call
        wait_until_idle() to block until motion completes.
        Returns True if the controller acknowledged with OK.
        """
        response = self._query(self._addr(slot, device, f"SK {position:.1f}"))
        return self._is_ok(response)

    def seek_cw(self, slot, device, position):
        """Seek forced into the up/clockwise direction only (command SKP)."""
        response = self._query(self._addr(slot, device, f"SKP {position:.1f}"))
        return self._is_ok(response)

    def seek_ccw(self, slot, device, position):
        """Seek forced into the down/counterclockwise direction only (command SKN)."""
        response = self._query(self._addr(slot, device, f"SKN {position:.1f}"))
        return self._is_ok(response)

    def stop(self, slot, device):
        self._query(self._addr(slot, device, "ST"))

    def jog_up(self, slot, device):
        """Move a tower up (or turntable clockwise) in Jog/Run mode."""
        self._query(self._addr(slot, device, "UP"))

    def jog_down(self, slot, device):
        """Move a tower down (or turntable counterclockwise) in Jog/Run mode."""
        self._query(self._addr(slot, device, "DN"))

    def clockwise(self, slot, device):
        self._query(self._addr(slot, device, "CW"))

    def counter_clockwise(self, slot, device):
        self._query(self._addr(slot, device, "CC"))

    def position(self, slot, device):
        """Return the current position as a float (cm or degrees)."""
        response = self._query(self._addr(slot, device, "CP?"))
        return self._parse_position(response)

    def direction(self, slot, device):
        """Returns -1 (moving down/CCW), 0 (stopped), or +1 (moving up/CW)."""
        return int(self._query(self._addr(slot, device, "DIR?")))

    def set_limits(self, slot, device, lower, upper):
        self._query(self._addr(slot, device, f"LL {lower}"))
        self._query(self._addr(slot, device, f"UL {upper}"))

    def set_speed(self, slot, device, preset):
        """Select a speed preset 1-8."""
        if not 1 <= preset <= 8:
            raise EMCenterError("Speed preset must be between 1 and 8")
        self._query(self._addr(slot, device, f"S{preset}"))

    def acceleration(self, slot, device, seconds):
        """Set acceleration/deceleration time (0.1-30.0 s)."""
        self._query(self._addr(slot, device, f"ACC {seconds}"))

    # ------------------------------------------------------------
    # Motion -- multiple axes at once
    # ------------------------------------------------------------

    def seek_many(self, moves):
        """
        Kick off simultaneous moves. moves is an iterable of
        (slot, device, position) tuples. Each SK is sent back-to-back
        (the moves start effectively together); follow with
        wait_all_idle() to block until every axis has arrived.

        Example:
            em.seek_many([(1, "A", 250), (1, "B", 250), (2, "A", 250)])
            em.wait_all_idle([(1, "A"), (1, "B"), (2, "A")])
        """
        results = {}
        for slot, device, position in moves:
            results[(slot, device)] = self.seek(slot, device, position)
        return results

    def wait_all_idle(self, axes, poll_interval=0.25, timeout=180, start_settle=0.5):
        """
        Block until every axis in `axes` (an iterable of (slot, device)
        tuples) reports DIR? == 0. Raises EMCenterError on timeout,
        stopping whichever axes are still moving.

        start_settle: delay (seconds) before the first status check.
        Immediately after a seek/seek_cw/seek_ccw command is sent, the
        controller can take a moment to actually flag the axis as
        moving. Without this delay, the very first DIR? poll can still
        read the leftover "idle" status from before the move started --
        so this method returns instantly, as if the move had already
        completed, while the axis is still in transit. This was the
        root cause of Normal Scan's Leg 3/Leg 4 (turntable return to 0)
        completing back-to-back without actually waiting for the
        turntable to arrive.
        """
        start = time.time()
        pending = set(axes)

        if start_settle:
            time.sleep(start_settle)

        while pending:
            for axis in list(pending):
                slot, device = axis
                if self.direction(slot, device) == 0:
                    pending.discard(axis)

            if not pending:
                return

            if time.time() - start > timeout:
                for slot, device in pending:
                    self.stop(slot, device)
                raise EMCenterError(
                    f"Timed out waiting for axes to stop: {sorted(pending)}"
                )

            time.sleep(poll_interval)

    # ------------------------------------------------------------
    # Polarization (towers only)
    # ------------------------------------------------------------

    def vertical(self, slot, device):
        self._query(self._addr(slot, device, "PV"))

    def horizontal(self, slot, device):
        self._query(self._addr(slot, device, "PH"))

    def polarization(self, slot, device):
        """Return 'VERTICAL' or 'HORIZONTAL'."""
        response = self._query(self._addr(slot, device, "P?"))
        return "HORIZONTAL" if response.strip() == "1" else "VERTICAL"

    # ------------------------------------------------------------
    # Scanning
    # ------------------------------------------------------------

    def set_scan_cycles(self, slot, device, cycles):
        self._query(self._addr(slot, device, f"CY {cycles}"))

    def scan(self, slot, device):
        self._query(self._addr(slot, device, "SC"))

    # ------------------------------------------------------------
    # Errors
    # ------------------------------------------------------------

    def errors(self, slot, device):
        value = int(self._query(self._addr(slot, device, "ERR?")))
        if value == 0:
            return []
        return [msg for bit, msg in ERROR_MAP.items() if value & (1 << bit)]

    def raise_if_error(self, slot, device):
        errs = self.errors(slot, device)
        if errs:
            raise EMCenterError(f"({slot}{device}) error: {', '.join(errs)}")

    # ------------------------------------------------------------
    # Convenience: seek + wait in one call
    # ------------------------------------------------------------

    def move_to(self, slot, device, position, timeout=180):
        """Blocking single-axis move: seek then wait_until_idle."""
        self.seek(slot, device, position)
        self.wait_until_idle(slot, device, timeout=timeout)

    def wait_until_idle(self, slot, device, poll_interval=0.25, timeout=180):
        self.wait_all_idle([(slot, device)], poll_interval, timeout)

    # ------------------------------------------------------------
    # Identification / lifecycle
    # ------------------------------------------------------------

    def identify(self):
        return self._query("*IDN?")

    def reset(self):
        self._query("*RST")

    def close(self):
        self.disconnect()

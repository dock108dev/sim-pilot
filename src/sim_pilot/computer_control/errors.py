"""Typed failures at the computer-control boundary."""


class ComputerControlError(RuntimeError):
    """Base desktop-control error."""


class StaleDesktopFrameError(ComputerControlError):
    """The intended input no longer belongs to a fresh frame."""


class UnsafeInputTargetError(ComputerControlError):
    """The intended target is outside the verified game surface."""

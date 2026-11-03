"""Compatibility imports; implementation moved to background_subtraction.py."""
from compat_records import MISSING
from compat_cv import find_contours
from background_subtraction import BackgroundFilter, BackgroundSubtractor, make_filter
__all__ = ['BackgroundFilter', 'BackgroundSubtractor', 'make_filter']

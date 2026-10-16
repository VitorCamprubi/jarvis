"""Is a full-screen app (game, video, presentation) in front? (ADR-045)

Windows answers this itself, for deciding when to hold notifications back.
"""

import ctypes

QUNS_BUSY = 2  # a full-screen app is in front
QUNS_RUNNING_D3D_FULL_SCREEN = 3  # an exclusive full-screen game
QUNS_PRESENTATION_MODE = 4
FULL_SCREEN_STATES = {QUNS_BUSY, QUNS_RUNNING_D3D_FULL_SCREEN, QUNS_PRESENTATION_MODE}


def full_screen_app_in_front() -> bool:
    state = ctypes.c_int()
    if ctypes.windll.shell32.SHQueryUserNotificationState(ctypes.byref(state)) != 0:
        return False  # the query failed: keep the HUD where it is
    return state.value in FULL_SCREEN_STATES

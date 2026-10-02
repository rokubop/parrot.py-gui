import numpy as np

class FrameStats:
    """dBFS and spectral flux of every detection frame so far. A frame's stats
    never change, so each threshold recalculation only adds the new frames
    instead of rebuilding the arrays from all of them."""

    def __init__(self):
        self.dBFS = np.empty(0)
        self.spectral_flux = np.empty(0)
        self.last_frame = None

    def update(self, detection_frames):
        known = len(self.dBFS)
        # The recorder cuts frames off the end on pause and clear. Start over if that happened.
        if known > len(detection_frames) or (known > 0 and detection_frames[known - 1] is not self.last_frame):
            self.__init__()
            known = 0

        new_frames = detection_frames[known:]
        if new_frames:
            self.dBFS = np.concatenate([self.dBFS, [frame.dBFS for frame in new_frames]])
            self.spectral_flux = np.concatenate([self.spectral_flux, [frame.spectral_flux for frame in new_frames]])
            self.last_frame = detection_frames[-1]
        return self.dBFS, self.spectral_flux

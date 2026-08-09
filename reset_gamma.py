"""One-shot: wipe stacked gamma ramps back to neutral 0.5/0.5/1.0."""

from gamma_control import hard_reset

if __name__ == "__main__":
    applied = hard_reset(all_displays=True)
    print("Hard reset applied to:", applied)
